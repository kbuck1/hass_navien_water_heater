import asyncio
import enum
import json
import logging
import uuid
from datetime import datetime, timedelta
import AWSIoTPythonSDK.MQTTLib as mqtt
import aiohttp

_LOGGER = logging.getLogger(__name__)


# Temperature conversion helpers
def _decode_half_degree_celsius(raw: int | float) -> float:
    """Decode half-degree Celsius encoding to actual Celsius.
    
    Used by MGPP display temps and Legacy Celsius devices.
    Wire encoding: raw = °C × 2
    """
    try:
        return float(raw) / 2.0
    except (TypeError, ValueError):
        return 0.0


def _decode_tenth_degree_celsius(raw: int | float) -> float:
    """Decode tenth-degree Celsius encoding to actual Celsius.
    
    Used by MGPP diagnostic/sensor temperatures.
    Wire encoding: raw = °C × 10
    """
    try:
        return float(raw) / 10.0
    except (TypeError, ValueError):
        return 0.0


def _encode_half_degree_celsius(celsius: float) -> int:
    """Encode Celsius to half-degree wire format.
    
    Used for outbound temperature commands to MGPP and Legacy Celsius devices.
    """
    return int(round(celsius * 2))


class NavilinkAccountCoordinator:
    """Coordinator that manages all gateways for a Navien account."""

    # The Navien server.
    navienWebServer = "https://nlus.naviensmartcontrol.com/api/v2"

    def __init__(self, userId, passwd, polling_interval=15, aws_cert_path="AmazonRootCA1.pem"):
        """
        Construct a new 'NavilinkAccountCoordinator' object.

        :param userId: The user ID used to log in to the mobile application
        :param passwd: The corresponding user's password
        :param polling_interval: How often to poll for updates
        :param aws_cert_path: Path to AWS IoT certificate
        """
        _LOGGER.debug("Initializing NaviLink account coordinator")
        self.userId = userId
        self.passwd = passwd
        self.polling_interval = polling_interval
        self.aws_cert_path = aws_cert_path
        self.user_info = None
        self.device_info_list = []
        self.gateways = {}  # mac_address -> NavilinkConnect
        self._disabled_devices = set()  # Set of device identifiers that should not be polled

    @property
    def devices(self):
        """Get all devices across all gateways."""
        all_devices = {}
        for gateway in self.gateways.values():
            for device_id, device in gateway.devices.items():
                all_devices[device_id] = device
        return all_devices

    async def login(self):
        """
        Login to the REST API and get device list.
        Returns list of device info for validation purposes.
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(
                NavilinkAccountCoordinator.navienWebServer + "/user/sign-in",
                json={"userId": self.userId, "password": self.passwd}
            ) as response:
                if response.status != 200:
                    raise UnableToConnect("Unexpected response during login")
                response_data = await response.json()
                if response_data.get('msg', '') == "USER_NOT_FOUND":
                    raise UserNotFound("Unable to log in with given credentials")
                try:
                    self.user_info = response_data["data"]
                except KeyError:
                    raise NoResponseData("Unexpected problem while retrieving user data")

                return await self._get_device_list()

    async def _get_device_list(self):
        """Get list of devices for the given user credentials."""
        headers = {"Authorization": self.user_info.get("token", {}).get("accessToken", "")}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(
                NavilinkAccountCoordinator.navienWebServer + "/device/list",
                json={"offset": 0, "count": 20, "userId": self.userId}
            ) as response:
                if response.status != 200:
                    raise UnableToConnect("Unexpected response while retrieving device list")
                response_data = await response.json()
                try:
                    self.device_info_list = response_data["data"]
                    _LOGGER.debug("Response data: " + str(response_data))
                except KeyError:
                    raise NoResponseData("Unexpected problem while retrieving device list")

                return self.device_info_list

    async def start(self):
        """Start the coordinator and all gateway connections."""
        if self.polling_interval > 0:
            await self.login()
            
            if not self.device_info_list:
                raise NoNavienDevices("No Navien devices found with the given credentials")

            # Create a NavilinkConnect for each gateway
            for device_info in self.device_info_list:
                mac_address = device_info.get("deviceInfo", {}).get("macAddress", "")
                if mac_address and mac_address not in self.gateways:
                    gateway = NavilinkConnect(
                        user_info=self.user_info,
                        device_info=device_info,
                        polling_interval=self.polling_interval,
                        aws_cert_path=self.aws_cert_path,
                        coordinator=self
                    )
                    self.gateways[mac_address] = gateway
                    await gateway.start()

            if not self.devices:
                raise NoNavienDevices("No Navien devices found with the given credentials")

            return self.devices
        else:
            # Just login for validation purposes
            return await self.login()

    async def disconnect(self):
        """Disconnect all gateways."""
        for gateway in self.gateways.values():
            await gateway.disconnect()
        self.gateways.clear()

    def is_device_polling_disabled(self, device_identifier):
        """Check if polling is disabled for a device.
        
        Args:
            device_identifier: The unique identifier for the device (mac_address or mac_address_channel)
        
        Returns:
            True if polling is disabled for this device, False otherwise
        """
        return device_identifier in self._disabled_devices

    def set_device_polling_disabled(self, device_identifier, disabled):
        """Enable or disable polling for a specific device.
        
        Args:
            device_identifier: The unique identifier for the device
            disabled: True to disable polling, False to enable polling
        """
        if disabled:
            self._disabled_devices.add(device_identifier)
            _LOGGER.debug(f"Disabled polling for device: {device_identifier}")
        else:
            self._disabled_devices.discard(device_identifier)
            _LOGGER.debug(f"Enabled polling for device: {device_identifier}")

    def set_disabled_devices(self, device_identifiers):
        """Set the complete set of devices that should not be polled.
        
        Args:
            device_identifiers: Set or list of device identifiers to disable polling for
        """
        self._disabled_devices = set(device_identifiers)
        _LOGGER.debug(f"Updated disabled devices: {self._disabled_devices}")


class NavilinkConnect:
    """Manages connection to a single NaviLink gateway."""

    # Connection health thresholds
    MAX_CONSECUTIVE_FAILURES = 3
    STALENESS_TIMEOUT_MULTIPLIER = 4

    def __init__(self, user_info, device_info, polling_interval=15, aws_cert_path="AmazonRootCA1.pem", 
                 subscribe_all_topics=False, coordinator=None):
        """
        Construct a new 'NavilinkConnect' object for a single gateway.

        :param user_info: User authentication info from login
        :param device_info: Device info for this gateway
        :param polling_interval: How often to poll for updates
        :param aws_cert_path: Path to AWS IoT certificate
        :param coordinator: Parent NavilinkAccountCoordinator
        """
        _LOGGER.debug("Initializing NaviLink gateway connection")
        self.user_info = user_info
        self.device_info = device_info
        self.polling_interval = polling_interval
        self.aws_cert_path = aws_cert_path
        self.subscribe_all_topics = subscribe_all_topics
        self.coordinator = coordinator
        self.loop = asyncio.get_running_loop()
        self.connected = False
        self.shutting_down = False
        self.client = None
        self.client_id = ""
        self.topics = None
        self.messages = None
        self.devices = {}  # Renamed from channels
        self.disconnect_event = asyncio.Event()
        self.response_events = {}
        self.client_lock = asyncio.Lock()
        self.last_poll = None
        self.last_data_received = None
        self.consecutive_poll_failures = 0
        self.device_type = int(self.device_info.get("deviceInfo", {}).get("deviceType", 1))

    @property
    def is_mgpp(self) -> bool:
        """Public flag indicating if this device uses the MGPP protocol."""
        try:
            return self._uses_mgpp_protocol()
        except Exception:
            return False

    @property
    def mac_address(self):
        """Get the MAC address of this gateway."""
        return self.device_info.get("deviceInfo", {}).get("macAddress", "")

    @property
    def device_name(self):
        """Get the device name of this gateway."""
        return self.device_info.get("deviceInfo", {}).get("deviceName", "Unknown")

    def _uses_mgpp_protocol(self):
        """
        Determine if the device uses the MGPP protocol.
        Currently, only device type 52 (NWP500) uses MGPP protocol.
        """
        return self.device_type == 52

    async def start(self):
        """Start the gateway connection."""
        if self.polling_interval > 0:
            while not self.connected and not self.shutting_down:
                try:
                    await self._connect_aws_mqtt()
                except (NoAccessKey, UnableToConnect, UserNotFound, NoResponseData, NoChannelInformation) as e:
                    # Fatal errors - don't retry, fail immediately
                    _LOGGER.error("Fatal connection error during start up: " + str(e))
                    raise
                except Exception as e:
                    # Transient errors - retry after delay
                    _LOGGER.error("Transient connection error during start up: " + str(e))
                    await asyncio.sleep(15)
                else:
                    asyncio.create_task(self._start())
                    if len(self.devices) > 0:
                        return self.devices
                    else:
                        raise NoNavienDevices("No Navien devices found for this gateway")

    async def _start(self):
        if not self.shutting_down:
            tasks = [
                asyncio.create_task(self._poll_mqtt_server(), name="Poll MQTT Server"),
                asyncio.create_task(self._server_connection_lost(), name="Connection Lost Event"),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for task in done:
                name = task.get_name()
                try:
                    task.result()
                except Exception as e:
                    _LOGGER.error(name + ": " + str(type(e).__name__) + ": " + str(e))
            for task in pending:
                task.cancel()
            if not self.shutting_down:
                _LOGGER.warning("Connection to AWS IOT Navilink server reset, reconnecting in 15 seconds")
                self.connected = False
                self.consecutive_poll_failures = 0
                self.last_data_received = None
                await asyncio.sleep(15)
                asyncio.create_task(self.start())

    async def _connect_aws_mqtt(self):
        self.client_id = str(uuid.uuid4())
        if self._uses_mgpp_protocol():
            self.topics = MgppTopics(self.user_info, self.device_info, self.client_id)
            self.messages = MgppMessages(self.device_info, self.client_id, self.topics)
        else:
            self.topics = Topics(self.user_info, self.device_info, self.client_id)
            self.messages = Messages(self.device_info, self.client_id, self.topics)
        
        accessKeyId = self.user_info.get("token", {}).get("accessKeyId", None)
        secretKey = self.user_info.get("token", {}).get("secretKey", None)
        sessionToken = self.user_info.get("token", {}).get("sessionToken", None)

        if accessKeyId and secretKey and sessionToken:
            self.client = mqtt.AWSIoTMQTTClient(
                clientID=self.client_id, protocolType=4, useWebsocket=True, cleanSession=True
            )
            self.client.configureEndpoint(
                hostName='a1t30mldyslmuq-ats.iot.us-east-1.amazonaws.com', portNumber=443
            )
            self.client.configureUsernamePassword(username='?SDK=Android&Version=2.16.12', password=None)
            self.client.configureLastWill(
                topic=self.topics.app_connection(),
                payload=json.dumps(self.messages.last_will(), separators=(',', ':')),
                QoS=1, retain=False
            )
            await self.loop.run_in_executor(None, self.client.configureCredentials, self.aws_cert_path)
            self.client.configureIAMCredentials(
                AWSAccessKeyID=accessKeyId, AWSSecretAccessKey=secretKey, AWSSessionToken=sessionToken
            )
            self.client.configureConnectDisconnectTimeout(5)
            self.client.onOffline = self._on_offline
            self.client.onOnline = self._on_online
            await self.loop.run_in_executor(None, self.client.connect)
            await self._subscribe_to_topics()
            if not len(self.devices):
                if self._uses_mgpp_protocol():
                    await self._get_mgpp_device_info()
                else:
                    await self._get_device_info()
            await self._get_device_status_all(wait_for_response=True)
            self.last_poll = datetime.now()
            self.last_data_received = datetime.now()
            self.consecutive_poll_failures = 0
        else:
            raise NoAccessKey("Missing Access key, Secret key, or Session token")

    async def _poll_mqtt_server(self):
        time_delta = 0
        while self.connected and not self.shutting_down:
            if time_delta < self.polling_interval:
                interval = self.polling_interval - time_delta
            else:
                interval = 0.1
            await asyncio.sleep(interval)

            if self._is_connection_stale():
                _LOGGER.warning("Connection appears stale - no data received recently, triggering reconnection")
                raise StaleConnectionError("No data received within staleness timeout")

            pre_poll = datetime.now()
            if not self.client_lock.locked():
                # Check if all devices are disabled - skip polling entirely
                all_disabled = all(
                    self.coordinator and self.coordinator.is_device_polling_disabled(device.device_identifier)
                    for device in self.devices.values()
                ) if self.devices else False
                
                if all_disabled:
                    _LOGGER.debug("All devices for this gateway are disabled, skipping poll")
                else:
                    poll_successful = await self._get_device_status_all_with_tracking()
                    if not poll_successful:
                        self.consecutive_poll_failures += 1
                        _LOGGER.warning(
                            f"Poll failed, consecutive failures: {self.consecutive_poll_failures}/{self.MAX_CONSECUTIVE_FAILURES}"
                        )
                        if self.consecutive_poll_failures >= self.MAX_CONSECUTIVE_FAILURES:
                            _LOGGER.error("Too many consecutive poll failures, triggering reconnection")
                            raise StaleConnectionError("Too many consecutive poll failures")
                    else:
                        if self.consecutive_poll_failures > 0:
                            _LOGGER.debug(
                                f"Poll succeeded after {self.consecutive_poll_failures} failures, resetting counter"
                            )
                        self.consecutive_poll_failures = 0
                    for device_num, device in self.devices.items():
                        _LOGGER.debug(f"Device {device_num} status after polling: {device.channel_status}")
            self.last_poll = datetime.now()
            time_delta = (self.last_poll - pre_poll).total_seconds()
        if not self.shutting_down:
            raise PollingError("Polling of AWS IOT Navilink server completed")

    def _is_connection_stale(self):
        """Check if the connection appears stale based on last data received."""
        if self.last_data_received is None:
            return False

        staleness_timeout = timedelta(seconds=self.polling_interval * self.STALENESS_TIMEOUT_MULTIPLIER)
        time_since_data = datetime.now() - self.last_data_received

        if time_since_data > staleness_timeout:
            _LOGGER.debug(
                f"Data staleness check: last data {time_since_data.total_seconds():.1f}s ago, "
                f"timeout is {staleness_timeout.total_seconds():.1f}s"
            )
            return True
        return False

    async def _get_device_status_all_with_tracking(self):
        """Poll for device status and track if responses are received."""
        try:
            await self._get_device_status_all(wait_for_response=True)
            return True
        except asyncio.TimeoutError:
            _LOGGER.debug("Poll request timed out waiting for response")
            return False
        except Exception as e:
            _LOGGER.debug(f"Poll request failed: {e}")
            return False

    async def _server_connection_lost(self):
        await self.disconnect_event.wait()
        self.disconnect_event.clear()
        raise DisconnectEvent("Disconnected from Navilink server...")

    async def disconnect(self, shutting_down=True):
        if self.client and self.connected:
            self.shutting_down = shutting_down
            try:
                await self.loop.run_in_executor(None, self.client.disconnect)
            except Exception as e:
                _LOGGER.warning(f"Error during disconnect: {e}")

    def _on_online(self):
        self.connected = True

    def _on_offline(self):
        if not self.shutting_down:
            self.disconnect_event.set()

    async def async_subscribe(self, topic, QoS=1, callback=None):
        _LOGGER.debug("Subscribing to " + topic)
        try:
            def subscribe():
                self.client.subscribe(topic=topic, QoS=QoS, callback=callback)

            async with self.client_lock:
                await self.loop.run_in_executor(None, subscribe)
        except Exception as e:
            _LOGGER.debug("Error occurred in async_subscribe: " + str(e))
            await self.disconnect(shutting_down=False)

    async def async_publish(self, topic, payload, QoS=1, session_id=""):
        try:
            def publish():
                self.client.publish(topic=topic, payload=json.dumps(payload, separators=(',', ':')), QoS=QoS)

            async with self.client_lock:
                await self.loop.run_in_executor(None, publish)

            if response_event := self.response_events.get(session_id, None):
                try:
                    await asyncio.wait_for(response_event.wait(), timeout=self.polling_interval)
                except asyncio.TimeoutError:
                    _LOGGER.debug(f"Timeout waiting for response to session {session_id}")
                    response_event.clear()
                    self.response_events.pop(session_id, None)
                    raise
                except Exception as e:
                    _LOGGER.debug(f"Error waiting for response: {e}")
                    response_event.clear()
                    self.response_events.pop(session_id, None)
                    raise
                response_event.clear()
                self.response_events.pop(session_id, None)
        except asyncio.TimeoutError:
            raise
        except Exception as e:
            _LOGGER.debug("Error occurred in async_publish: " + str(e))
            if response_event := self.response_events.get(session_id, None):
                response_event.clear()
                self.response_events.pop(session_id, None)
            await self.disconnect(shutting_down=False)

    async def _subscribe_to_topics(self):
        if self._uses_mgpp_protocol():
            await self.async_subscribe(topic=self.topics.mgpp_default(), callback=self.handle_other)
            await self.async_subscribe(topic=self.topics.mgpp_res_did(), callback=self.handle_mgpp_did)
            await self.async_subscribe(topic=self.topics.mgpp_res(), callback=self.handle_mgpp_status)
            await self.async_subscribe(topic=self.topics.mgpp_res_rsv_rd(), callback=self.handle_mgpp_rsv)
            await self.async_subscribe(topic=self.topics.mgpp_ctrl_fail(), callback=self.handle_mgpp_ctrl_fail)
            await self.async_subscribe(topic=self.topics.app_connection(), callback=self.handle_mgpp_connection)
            await self.async_subscribe(topic=self.topics.mgpp_connection(), callback=self.handle_mgpp_connection)
            await self.async_subscribe(topic=self.topics.mgpp_disconnect(), callback=self.handle_mgpp_disconnect)
        else:
            await self.async_subscribe(topic=self.topics.channel_info_sub(), callback=self.handle_other)
            await self.async_subscribe(topic=self.topics.channel_info_res(), callback=self.handle_device_info)
            await self.async_subscribe(topic=self.topics.control_fail(), callback=self.handle_other)
            await self.async_subscribe(topic=self.topics.channel_status_sub(), callback=self.handle_other)
            await self.async_subscribe(topic=self.topics.channel_status_res(), callback=self.handle_device_status)
            await self.async_subscribe(topic=self.topics.connection(), callback=self.handle_other)
            await self.async_subscribe(topic=self.topics.disconnect(), callback=self.handle_other)
            if self.subscribe_all_topics:
                await self.async_subscribe(topic=self.topics.weekly_schedule_sub(), callback=self.handle_other)
                await self.async_subscribe(topic=self.topics.weekly_schedule_res(), callback=self.handle_weekly_schedule)
                await self.async_subscribe(topic=self.topics.simple_trend_sub(), callback=self.handle_other)
                await self.async_subscribe(topic=self.topics.simple_trend_res(), callback=self.handle_simple_trend)
                await self.async_subscribe(topic=self.topics.hourly_trend_sub(), callback=self.handle_other)
                await self.async_subscribe(topic=self.topics.hourly_trend_res(), callback=self.handle_hourly_trend)
                await self.async_subscribe(topic=self.topics.daily_trend_sub(), callback=self.handle_other)
                await self.async_subscribe(topic=self.topics.daily_trend_res(), callback=self.handle_daily_trend)
                await self.async_subscribe(topic=self.topics.monthly_trend_sub(), callback=self.handle_other)
                await self.async_subscribe(topic=self.topics.monthly_trend_res(), callback=self.handle_monthly_trend)

    async def _get_mgpp_device_info(self):
        """Initialize MGPP device by requesting DID and status information"""
        _LOGGER.debug("Initializing MGPP device...")

        if len(self.devices) == 0:
            channel_info = {
                "channelNumber": 1,
                "channel": {
                    "channelNumber": 1,
                    "channelName": "MGPP Channel",
                    "unitCount": 1
                },
                "temperatureType": TemperatureType.FAHRENHEIT.value,
                "setupDHWTempMin": 100,
                "setupDHWTempMax": 140
            }
            self.devices[1] = MgppDevice(1, channel_info, self, None)
            _LOGGER.debug("Created MGPP device")

        topic = self.topics.mgpp_st_did()
        payload = self.messages.mgpp_did()
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)

        topic = self.topics.mgpp_st()
        payload = self.messages.mgpp_status()
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)

        topic = self.topics.mgpp_st_rsv_rd()
        payload = self.messages.mgpp_rsv_rd()
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)

        if len(self.devices) == 0:
            raise NoChannelInformation("Unable to get MGPP device information")

    async def _get_device_info(self):
        """Get channel/device info for legacy devices."""
        topic = self.topics.start()
        payload = self.messages.channel_info()
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        if len(self.devices) == 0:
            raise NoChannelInformation("Unable to get channel information")

    async def _get_device_status_all(self, wait_for_response=False):
        """Get status for all devices on this gateway."""
        _LOGGER.debug(f"Getting device status for device type {self.device_type}, wait_for_response={wait_for_response}")
        if self._uses_mgpp_protocol():
            _LOGGER.debug("Using MGPP protocol for status requests")
            await self._get_mgpp_status_all(wait_for_response)
        else:
            _LOGGER.debug("Using legacy protocol for status requests")
            for device in self.devices.values():
                # Skip polling for disabled devices
                if self.coordinator and self.coordinator.is_device_polling_disabled(device.device_identifier):
                    _LOGGER.debug(f"Skipping disabled device {device.device_identifier}")
                    continue
                    
                topic = self.topics.channel_status_req()
                payload = self.messages.channel_status(device.channel_number, device.channel_info.get("unitCount", 1))
                session_id = self.get_session_id()
                payload["sessionID"] = session_id
                if wait_for_response:
                    self.response_events[session_id] = asyncio.Event()
                else:
                    session_id = ""
                await self.async_publish(topic=topic, payload=payload, session_id=session_id)

    async def _get_mgpp_status_all(self, wait_for_response=False):
        """Poll MGPP device for status and RSV data"""
        _LOGGER.debug("Polling MGPP device for status...")
        
        # Check if MGPP device is disabled
        for device in self.devices.values():
            if self.coordinator and self.coordinator.is_device_polling_disabled(device.device_identifier):
                _LOGGER.debug(f"Skipping disabled MGPP device {device.device_identifier}")
                return
        
        topic = self.topics.mgpp_st()
        payload = self.messages.mgpp_status()
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        _LOGGER.debug(f"Publishing status request to {topic} with session {session_id}")
        if wait_for_response:
            self.response_events[session_id] = asyncio.Event()
        else:
            session_id = ""
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)

        topic = self.topics.mgpp_st_rsv_rd()
        payload = self.messages.mgpp_rsv_rd()
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        if wait_for_response:
            self.response_events[session_id] = asyncio.Event()
        else:
            session_id = ""
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)

    async def _get_device_status(self, channel_number):
        """Get status for a specific device."""
        device = self.devices.get(channel_number, {})
        topic = self.topics.channel_status_req()
        payload = self.messages.channel_status(device.channel_number, device.channel_info.get("unitCount", 1))
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)

    async def _power_command(self, state, channel_number):
        """Unified power control command that routes to appropriate protocol implementation"""
        if self._uses_mgpp_protocol():
            await self._mgpp_power_command(state, channel_number)
        else:
            await self._legacy_power_command(state, channel_number)

    async def _legacy_power_command(self, state, channel_number):
        """Legacy protocol power control command"""
        state_num = 1 if state else 2
        topic = self.topics.control()
        payload = self.messages.power(state_num, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        await self._get_device_status(channel_number)

    async def _mgpp_power_command(self, state, channel_number):
        """MGPP power control command"""
        if not self._uses_mgpp_protocol():
            raise ValueError("MGPP power command only supported for MGPP protocol devices")

        topic = self.topics.mgpp_control()
        payload = self.messages.mgpp_power(state, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        await self._get_mgpp_status_all(wait_for_response=True)

    async def _hot_button_command(self, state, channel_number):
        """Hot button control command"""
        state_num = 1 if state else 2
        topic = self.topics.control()
        payload = self.messages.hot_button(state_num, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        await self._get_device_status(channel_number)

    async def _temperature_command(self, temp, channel_number):
        """Unified temperature control command that routes to appropriate protocol implementation"""
        if self._uses_mgpp_protocol():
            await self._mgpp_temperature_command(temp, channel_number)
        else:
            await self._legacy_temperature_command(temp, channel_number)

    async def _legacy_temperature_command(self, temp, channel_number):
        """Legacy protocol temperature control command"""
        topic = self.topics.control()
        payload = self.messages.temperature(temp, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        await self._get_device_status(channel_number)

    async def _mgpp_temperature_command(self, temp, channel_number):
        """MGPP temperature control command"""
        if not self._uses_mgpp_protocol():
            raise ValueError("MGPP temperature command only supported for MGPP protocol devices")

        topic = self.topics.mgpp_control()
        payload = self.messages.mgpp_temperature(temp, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        await self._get_mgpp_status_all(wait_for_response=True)

    async def _mgpp_operation_mode_command(self, mode, channel_number, days=None):
        """MGPP operation mode control command"""
        if not self._uses_mgpp_protocol():
            raise ValueError("MGPP operation mode only supported for MGPP protocol devices")

        topic = self.topics.mgpp_control()
        payload = self.messages.mgpp_operation_mode(mode, channel_number, days)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        await self._get_mgpp_status_all(wait_for_response=True)

    async def _mgpp_anti_legionella_command(self, state, channel_number):
        """MGPP anti-legionella control command"""
        if not self._uses_mgpp_protocol():
            raise ValueError("MGPP anti-legionella only supported for MGPP protocol devices")

        topic = self.topics.mgpp_control()
        payload = self.messages.mgpp_anti_legionella(state, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        await self._get_mgpp_status_all(wait_for_response=True)

    async def _mgpp_freeze_protection_command(self, state, channel_number):
        """MGPP freeze protection control command"""
        if not self._uses_mgpp_protocol():
            raise ValueError("MGPP freeze protection only supported for MGPP protocol devices")

        topic = self.topics.mgpp_control()
        payload = self.messages.mgpp_freeze_protection(state, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        await self._get_mgpp_status_all(wait_for_response=True)

    async def _mgpp_recirc_hot_button_command(self, state, channel_number):
        """MGPP recirculation hot button control command"""
        if not self._uses_mgpp_protocol():
            raise ValueError("MGPP recirculation hot button only supported for MGPP protocol devices")

        topic = self.topics.mgpp_control()
        payload = self.messages.mgpp_recirc_hot_button(state, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        await self._get_mgpp_status_all(wait_for_response=True)

    def get_session_id(self):
        return str(int(round((datetime.utcnow() - datetime(1970, 1, 1)).total_seconds() * 1000)))

    def _mark_data_received(self):
        """Mark that data was received, updating the connection health tracking."""
        self.last_data_received = datetime.now()
        _LOGGER.debug(f"Data received, updated last_data_received to {self.last_data_received}")

    def async_handle_device_info(self, client, userdata, message):
        """Handle channel info response for legacy devices."""
        response = json.loads(message.payload)
        _LOGGER.debug(f"Device info response: {response}")
        self._mark_data_received()
        channel_info = response.get("response", {})
        session_id = response.get("sessionID", "unknown")
        
        # Create NavilinkDevice for each channel, passing gateway info
        self.devices = {}
        for channel in channel_info.get("channelInfo", {}).get("channelList", []):
            channel_number = channel.get("channelNumber", 0)
            self.devices[channel_number] = NavilinkDevice(
                channel_number=channel_number,
                channel_info=channel.get("channel", {}),
                gateway=self
            )
        
        if response_event := self.response_events.get(session_id, None):
            response_event.set()

    def handle_device_info(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_device_info, client, userdata, message)

    def async_handle_device_status(self, client, userdata, message):
        """Handle channel status response for legacy devices."""
        response = json.loads(message.payload)
        self._mark_data_received()
        channel_status = response.get("response", {}).get("channelStatus", {})
        session_id = response.get("sessionID", "unknown")
        if device := self.devices.get(channel_status.get("channelNumber", 0), None):
            device.update_channel_status(channel_status.get("channel", {}))
        if response_event := self.response_events.get(session_id, None):
            response_event.set()

    def handle_device_status(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_device_status, client, userdata, message)

    def handle_weekly_schedule(self, client, userdata, message):
        _LOGGER.info("WEEKLY SCHEDULE: " + message.payload.decode('utf-8') + '\n')

    def handle_simple_trend(self, client, userdata, message):
        _LOGGER.info("SIMPLE TREND: " + message.payload.decode('utf-8') + '\n')

    def handle_hourly_trend(self, client, userdata, message):
        _LOGGER.info("HOURLY TREND: " + message.payload.decode('utf-8') + '\n')

    def handle_daily_trend(self, client, userdata, message):
        _LOGGER.info("DAILY TREND: " + message.payload.decode('utf-8') + '\n')

    def handle_monthly_trend(self, client, userdata, message):
        _LOGGER.info("MONTHLY TREND: " + message.payload.decode('utf-8') + '\n')

    def async_handle_mgpp_did(self, client, userdata, message):
        response = json.loads(message.payload)
        _LOGGER.debug("MGPP DID Response: " + json.dumps(response, indent=2))
        self._mark_data_received()
        session_id = response.get("sessionID", "unknown")

        if len(self.devices) > 0:
            device = list(self.devices.values())[0]
            if hasattr(device, 'did_features'):
                feature_data = response.get("response", {}).get("feature", {})
                device.did_features = feature_data
                _LOGGER.debug(f"Stored DID feature data: {feature_data}")

        if response_event := self.response_events.get(session_id, None):
            response_event.set()
        else:
            _LOGGER.debug(f"No response event found for session ID: {session_id}")

    def handle_mgpp_did(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_mgpp_did, client, userdata, message)

    def async_handle_mgpp_status(self, client, userdata, message):
        response = json.loads(message.payload)
        _LOGGER.debug("MGPP STATUS Response: " + json.dumps(response, indent=2))
        self._mark_data_received()
        session_id = response.get("sessionID", "unknown")
        if response_event := self.response_events.get(session_id, None):
            response_event.set()
            _LOGGER.debug(f"Set response event for session ID: {session_id}")
        else:
            _LOGGER.debug(f"No response event found for session ID: {session_id}")
        for device in self.devices.values():
            if hasattr(device, 'update_channel_status'):
                _LOGGER.debug(f"Updating device {device.channel_number} with status response")
                device.update_channel_status('status', response)

    def handle_mgpp_status(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_mgpp_status, client, userdata, message)

    def async_handle_mgpp_rsv(self, client, userdata, message):
        response = json.loads(message.payload)
        _LOGGER.debug("MGPP RSV Response: " + json.dumps(response, indent=2))
        self._mark_data_received()
        session_id = response.get("sessionID", "unknown")
        if response_event := self.response_events.get(session_id, None):
            response_event.set()
        else:
            _LOGGER.debug(f"No response event found for session ID: {session_id}")
        for device in self.devices.values():
            if hasattr(device, 'update_channel_status'):
                device.update_channel_status('rsv', response)

    def handle_mgpp_rsv(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_mgpp_rsv, client, userdata, message)

    def async_handle_mgpp_ctrl_fail(self, client, userdata, message):
        """Handle MGPP control failure notifications per spec"""
        response = json.loads(message.payload)
        _LOGGER.warning("MGPP Control Failure: " + json.dumps(response, indent=2))
        fail_code = response.get("response", {}).get("failCode", 0)
        if fail_code == 2:
            _LOGGER.error("Control interval exceeded - command rejected by platform")
        else:
            _LOGGER.warning(f"Control failure with code: {fail_code}")

    def handle_mgpp_ctrl_fail(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_mgpp_ctrl_fail, client, userdata, message)

    def async_handle_mgpp_connection(self, client, userdata, message):
        """Handle MGPP connection heartbeat events per spec"""
        response = json.loads(message.payload)
        _LOGGER.debug("MGPP Connection Event: " + json.dumps(response, indent=2))
        event_data = response.get("event", {})
        connection = event_data.get("connection", {})
        status = connection.get("status", 0)
        if status <= 0:
            _LOGGER.warning("Device connection status indicates disconnect (status <= 0)")

    def handle_mgpp_connection(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_mgpp_connection, client, userdata, message)

    def async_handle_mgpp_disconnect(self, client, userdata, message):
        """Handle MGPP disconnect broadcast per spec"""
        _LOGGER.warning("MGPP Disconnect Broadcast received - device MQTT session dropped")

    def handle_mgpp_disconnect(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_mgpp_disconnect, client, userdata, message)

    def handle_other(self, client, userdata, message):
        _LOGGER.info(message.payload.decode('utf-8') + '\n')


class NavilinkDevice:
    """Represents a single water heater device (legacy protocol)."""

    def __init__(self, channel_number, channel_info, gateway) -> None:
        self.channel_number = channel_number
        self.channel_info = self.convert_channel_info(channel_info)
        self.gateway = gateway
        self.callbacks = []
        self.channel_status = {}
        self.unit_list = {}
        self.waiting_for_response = False

    @property
    def mac_address(self):
        """Get the MAC address of the gateway this device belongs to."""
        return self.gateway.mac_address

    @property
    def device_name(self):
        """Get the device name including channel number."""
        base_name = self.gateway.device_name
        return f"{base_name} CH{self.channel_number}"

    @property
    def device_identifier(self):
        """Get the unique identifier for this device (used in device registry)."""
        return f"{self.mac_address}_{self.channel_number}"

    @property
    def hub(self):
        """Backwards compatibility alias for gateway."""
        return self.gateway

    @property
    def is_celsius(self) -> bool:
        """Return True if device uses Celsius, False if Fahrenheit.
        
        Legacy devices can be configured for Celsius or Fahrenheit.
        Wire encoding differs: Celsius uses half-degree encoding, Fahrenheit is raw.
        """
        return self.channel_info.get("temperatureType", 2) != TemperatureType.FAHRENHEIT.value

    def register_callback(self, callback):
        self.callbacks.append(callback)

    def deregister_callback(self, callback):
        if self.callbacks:
            self.callbacks.pop(self.callbacks.index(callback))

    def update_channel_status(self, channel_status):
        self.channel_status = self.convert_channel_status(channel_status)
        if not self.waiting_for_response:
            self.publish_update()

    def publish_update(self):
        if len(self.callbacks) > 0:
            for callback in self.callbacks:
                self.gateway.loop.call_soon_threadsafe(callback)

    async def set_power_state(self, state):
        if not self.waiting_for_response:
            self.waiting_for_response = True
            try:
                await self.gateway._power_command(state, self.channel_number)
                self.publish_update()
            finally:
                self.waiting_for_response = False

    async def set_hot_button_state(self, state):
        if not self.waiting_for_response:
            self.waiting_for_response = True
            try:
                await self.gateway._hot_button_command(state, self.channel_number)
                self.publish_update()
            finally:
                self.waiting_for_response = False

    async def set_temperature(self, temp):
        """Set target temperature.
        
        Args:
            temp: Temperature in the device's native unit (Celsius or Fahrenheit).
                  For Celsius devices, this will be encoded as half-degree format.
                  For Fahrenheit devices, this is sent as-is.
        """
        if not self.waiting_for_response:
            self.waiting_for_response = True
            try:
                # Encode temperature for wire protocol
                if self.is_celsius:
                    # Celsius devices use half-degree encoding: raw = °C × 2
                    wire_temp = _encode_half_degree_celsius(temp)
                else:
                    # Fahrenheit devices send raw °F value
                    wire_temp = int(round(temp))
                await self.gateway._temperature_command(wire_temp, self.channel_number)
                self.publish_update()
            finally:
                self.waiting_for_response = False

    def convert_channel_status(self, channel_status):
        channel_status["powerStatus"] = channel_status["powerStatus"] == 1
        channel_status["onDemandUseFlag"] = channel_status["onDemandUseFlag"] == 1
        channel_status["avgCalorie"] = channel_status["avgCalorie"] / 2.0
        if self.channel_info.get("temperatureType", 2) == TemperatureType.CELSIUS.value:
            if channel_status["unitType"] in [
                DeviceSorting.NFC.value, DeviceSorting.NCB_H.value,
                DeviceSorting.NFB.value, DeviceSorting.NVW.value,
            ]:
                GIUFactor = 100
            else:
                GIUFactor = 10

            if channel_status["unitType"] in [
                DeviceSorting.NPE.value, DeviceSorting.NPN.value, DeviceSorting.NPE2.value,
                DeviceSorting.NCB.value, DeviceSorting.NFC.value, DeviceSorting.NCB_H.value,
                DeviceSorting.CAS_NPE.value, DeviceSorting.CAS_NPN.value, DeviceSorting.CAS_NPE2.value,
                DeviceSorting.NFB.value, DeviceSorting.NVW.value,
                DeviceSorting.CAS_NFB.value, DeviceSorting.CAS_NVW.value,
            ]:
                channel_status["DHWSettingTemp"] = round(channel_status["DHWSettingTemp"] / 2.0, 1)
                channel_status["avgInletTemp"] = round(channel_status["avgInletTemp"] / 2.0, 1)
                channel_status["avgOutletTemp"] = round(channel_status["avgOutletTemp"] / 2.0, 1)
                for i in range(channel_status.get("unitCount", 0)):
                    channel_status["unitInfo"]["unitStatusList"][i]["gasInstantUsage"] = round(
                        (channel_status["unitInfo"]["unitStatusList"][i]["gasInstantUsage"] * GIUFactor) / 10.0, 1
                    )
                    channel_status["unitInfo"]["unitStatusList"][i]["accumulatedGasUsage"] = round(
                        channel_status["unitInfo"]["unitStatusList"][i]["accumulatedGasUsage"] / 10.0, 1
                    )
                    channel_status["unitInfo"]["unitStatusList"][i]["DHWFlowRate"] = round(
                        channel_status["unitInfo"]["unitStatusList"][i]["DHWFlowRate"] / 10.0, 1
                    )
                    channel_status["unitInfo"]["unitStatusList"][i]["currentOutletTemp"] = round(
                        channel_status["unitInfo"]["unitStatusList"][i]["currentOutletTemp"] / 2.0, 1
                    )
                    channel_status["unitInfo"]["unitStatusList"][i]["currentInletTemp"] = round(
                        channel_status["unitInfo"]["unitStatusList"][i]["currentInletTemp"] / 2.0, 1
                    )
        elif self.channel_info.get("temperatureType", 2) == TemperatureType.FAHRENHEIT.value:
            if channel_status["unitType"] in [
                DeviceSorting.NFC.value, DeviceSorting.NCB_H.value,
                DeviceSorting.NFB.value, DeviceSorting.NVW.value,
            ]:
                GIUFactor = 10
            else:
                GIUFactor = 1

            if channel_status["unitType"] in [
                DeviceSorting.NPE.value, DeviceSorting.NPN.value, DeviceSorting.NPE2.value,
                DeviceSorting.NCB.value, DeviceSorting.NFC.value, DeviceSorting.NCB_H.value,
                DeviceSorting.CAS_NPE.value, DeviceSorting.CAS_NPN.value, DeviceSorting.CAS_NPE2.value,
                DeviceSorting.NFB.value, DeviceSorting.NVW.value,
                DeviceSorting.CAS_NFB.value, DeviceSorting.CAS_NVW.value,
            ]:
                for i in range(channel_status.get("unitCount", 0)):
                    channel_status["unitInfo"]["unitStatusList"][i]["gasInstantUsage"] = round(
                        channel_status["unitInfo"]["unitStatusList"][i]["gasInstantUsage"] * GIUFactor * 3.968, 1
                    )
                    channel_status["unitInfo"]["unitStatusList"][i]["accumulatedGasUsage"] = round(
                        channel_status["unitInfo"]["unitStatusList"][i]["accumulatedGasUsage"] * 35.314667 / 10.0, 1
                    )
                    channel_status["unitInfo"]["unitStatusList"][i]["DHWFlowRate"] = round(
                        channel_status["unitInfo"]["unitStatusList"][i]["DHWFlowRate"] / 37.85, 1
                    )

        return channel_status

    def convert_channel_info(self, channel_info):
        if channel_info.get("temperatureType", 2) == TemperatureType.CELSIUS.value:
            channel_info["setupDHWTempMin"] = round(channel_info["setupDHWTempMin"] / 2.0, 1)
            channel_info["setupDHWTempMax"] = round(channel_info["setupDHWTempMax"] / 2.0, 1)
        return channel_info

    def is_available(self):
        return self.gateway.connected


class MgppDevice:
    """Represents a single MGPP water heater device."""

    def __init__(self, channel_number, channel_info, gateway, did_features=None) -> None:
        self.channel_number = channel_number
        self.channel_info = self.convert_channel_info(channel_info)
        self.gateway = gateway
        self.callbacks = []
        self.channel_status = {}
        self.raw_responses = {
            'did': None,
            'status': None,
            'rsv': None
        }
        self.did_features = did_features or {}
        self.waiting_for_response = False
        self.vacation_days = 7

    @property
    def mac_address(self):
        """Get the MAC address of the gateway this device belongs to."""
        return self.gateway.mac_address

    @property
    def device_name(self):
        """Get the device name (MGPP devices don't have channel numbers in name)."""
        return self.gateway.device_name

    @property
    def device_identifier(self):
        """Get the unique identifier for this device (used in device registry)."""
        # MGPP devices use just MAC since there's only one device per gateway
        return self.mac_address

    @property
    def hub(self):
        """Backwards compatibility alias for gateway."""
        return self.gateway

    @property
    def is_celsius(self) -> bool:
        """Return True - MGPP devices always use Celsius.
        
        MGPP devices always use half-degree Celsius wire encoding.
        The temperatureType field is just a UI display preference.
        """
        return True

    # Temperature properties - decode raw values to Celsius
    @property
    def dhw_temperature(self) -> float:
        """Current DHW temperature in Celsius."""
        return _decode_half_degree_celsius(self.channel_status.get('dhwTemperature', 0))

    @property
    def dhw_temperature_setting(self) -> float:
        """Target DHW temperature setting in Celsius."""
        return _decode_half_degree_celsius(self.channel_status.get('dhwTemperatureSetting', 0))

    @property
    def dhw_temperature_min(self) -> float:
        """Minimum DHW temperature in Celsius."""
        return _decode_half_degree_celsius(self.did_features.get('dhwTemperatureMin', 0))

    @property
    def dhw_temperature_max(self) -> float:
        """Maximum DHW temperature in Celsius."""
        return _decode_half_degree_celsius(self.did_features.get('dhwTemperatureMax', 0))

    # Diagnostic temperature properties - tenth-degree encoding
    @property
    def tank_upper_temperature(self) -> float:
        """Tank upper temperature in Celsius."""
        return _decode_tenth_degree_celsius(self.channel_status.get('tankUpperTemperature', 0))

    @property
    def tank_lower_temperature(self) -> float:
        """Tank lower temperature in Celsius."""
        return _decode_tenth_degree_celsius(self.channel_status.get('tankLowerTemperature', 0))

    @property
    def ambient_temperature(self) -> float:
        """Ambient temperature in Celsius."""
        return _decode_tenth_degree_celsius(self.channel_status.get('ambientTemperature', 0))

    @property
    def discharge_temperature(self) -> float:
        """Discharge temperature in Celsius."""
        return _decode_tenth_degree_celsius(self.channel_status.get('dischargeTemperature', 0))

    @property
    def suction_temperature(self) -> float:
        """Suction temperature in Celsius."""
        return _decode_tenth_degree_celsius(self.channel_status.get('suctionTemperature', 0))

    @property
    def evaporator_temperature(self) -> float:
        """Evaporator temperature in Celsius."""
        return _decode_tenth_degree_celsius(self.channel_status.get('evaporatorTemperature', 0))

    @property
    def current_superheat(self) -> float:
        """Current superheat in Celsius."""
        return _decode_tenth_degree_celsius(self.channel_status.get('currentSuperHeat', 0))

    @property
    def target_superheat(self) -> float:
        """Target superheat in Celsius."""
        return _decode_tenth_degree_celsius(self.channel_status.get('targetSuperHeat', 0))

    @property
    def recirc_faucet_temperature(self) -> float:
        """Recirculation faucet temperature in Celsius."""
        return _decode_tenth_degree_celsius(self.channel_status.get('recircFaucetTemperature', 0))

    def register_callback(self, callback):
        self.callbacks.append(callback)

    def deregister_callback(self, callback):
        if self.callbacks:
            self.callbacks.pop(self.callbacks.index(callback))

    def update_channel_status(self, response_type, response_data):
        """Update channel status with raw response data (no conversion here)."""
        self.raw_responses[response_type] = response_data
        _LOGGER.debug(f"MGPP {response_type.upper()} Response: {json.dumps(response_data, indent=2)}")

        if response_type == 'status' and 'response' in response_data:
            status_data = response_data['response'].get('status', {})
            self.channel_status = status_data
        elif response_type == 'status':
            self.channel_status = response_data

        if not self.waiting_for_response:
            self.publish_update()

    def publish_update(self):
        if len(self.callbacks) > 0:
            for callback in self.callbacks:
                self.gateway.loop.call_soon_threadsafe(callback)

    async def set_power_state(self, state):
        """Set MGPP device power state"""
        if not self.waiting_for_response:
            self.waiting_for_response = True
            try:
                await self.gateway._mgpp_power_command(state, self.channel_number)
                self.publish_update()
            finally:
                self.waiting_for_response = False

    async def set_temperature(self, temp_celsius):
        """Set MGPP device temperature.
        
        Args:
            temp_celsius: Temperature in Celsius (MGPP always uses Celsius).
        """
        if not self.waiting_for_response:
            self.waiting_for_response = True
            try:
                # MGPP always uses half-degree Celsius encoding
                raw_temp = _encode_half_degree_celsius(temp_celsius)
                await self.gateway._mgpp_temperature_command(raw_temp, self.channel_number)
                self.publish_update()
            finally:
                self.waiting_for_response = False

    async def set_operation_mode(self, mode, days=None):
        """Set MGPP operation mode"""
        if not self.waiting_for_response:
            self.waiting_for_response = True
            try:
                vacation_days = days if days is not None else self.vacation_days
                await self.gateway._mgpp_operation_mode_command(mode, self.channel_number, vacation_days)
                self.publish_update()
            finally:
                self.waiting_for_response = False

    async def set_anti_legionella_state(self, state):
        """Set MGPP anti-legionella state"""
        if not self.waiting_for_response:
            self.waiting_for_response = True
            try:
                await self.gateway._mgpp_anti_legionella_command(state, self.channel_number)
                self.publish_update()
            finally:
                self.waiting_for_response = False

    async def set_freeze_protection_state(self, state):
        """Set MGPP freeze protection state"""
        if not self.waiting_for_response:
            self.waiting_for_response = True
            try:
                await self.gateway._mgpp_freeze_protection_command(state, self.channel_number)
                self.publish_update()
            finally:
                self.waiting_for_response = False

    @property
    def supports_recirculation(self):
        """Check if device supports recirculation (Hot Button)."""
        # RecirculationUse: 1=NOT_USE, 2=USE
        return self.did_features.get('recirculationUse', 0) == 2

    async def set_recirc_hot_button_state(self, state):
        """Set MGPP recirculation hot button state"""
        if not self.waiting_for_response:
            self.waiting_for_response = True
            try:
                await self.gateway._mgpp_recirc_hot_button_command(state, self.channel_number)
                self.publish_update()
            finally:
                self.waiting_for_response = False

    def get_error_message(self):
        """Get human-readable error message if device has errors"""
        if not self.channel_status.get('hasError', False):
            return None

        error_code = self.channel_status.get('errorCode', 0)
        sub_error_code = self.channel_status.get('subErrorCode', 0)
        fault1 = self.channel_status.get('faultStatus1', 0)
        fault2 = self.channel_status.get('faultStatus2', 0)

        if error_code != 0:
            return f"Error Code: {error_code} (Sub: {sub_error_code})"
        elif fault1 != 0 or fault2 != 0:
            return f"Fault Status: {fault1}, {fault2}"

        return "Unknown error condition"

    def get_status_summary(self):
        """Get a summary of the current device status"""
        if not self.channel_status:
            return "No status data available"

        status_parts = []

        if self.channel_status.get('powerStatus', False):
            status_parts.append("ON")
        else:
            status_parts.append("OFF")

        temp = self.channel_status.get('dhwTemperature', 0)
        target_temp = self.channel_status.get('dhwTemperatureSetting', 0)
        status_parts.append(f"Temp: {temp}°F (Target: {target_temp}°F)")

        if self.channel_status.get('hasError', False):
            error_msg = self.get_error_message()
            status_parts.append(f"ERROR: {error_msg}")

        if self.channel_status.get('isHeating', False):
            status_parts.append("HEATING")

        if self.channel_status.get('isEcoMode', False):
            status_parts.append("ECO MODE")

        return " | ".join(status_parts)

    def convert_channel_info(self, channel_info):
        """Convert channel info to include required fields for water_heater.py compatibility"""
        if "temperatureType" not in channel_info:
            channel_info["temperatureType"] = TemperatureType.FAHRENHEIT.value

        if "setupDHWTempMin" not in channel_info:
            channel_info["setupDHWTempMin"] = 100
        if "setupDHWTempMax" not in channel_info:
            channel_info["setupDHWTempMax"] = 140

        if channel_info.get("temperatureType", TemperatureType.FAHRENHEIT.value) == TemperatureType.CELSIUS.value:
            channel_info["setupDHWTempMin"] = round(channel_info["setupDHWTempMin"] / 2.0, 1)
            channel_info["setupDHWTempMax"] = round(channel_info["setupDHWTempMax"] / 2.0, 1)

        return channel_info

    def is_available(self):
        return self.gateway.connected


class MgppTopics:
    def __init__(self, user_info, device_info, client_id) -> None:
        self.user_seq = str(user_info.get("userInfo", {}).get("userSeq", ""))
        self.mac_address = device_info.get("deviceInfo", {}).get("macAddress", "")
        self.home_seq = str(device_info.get("deviceInfo", {}).get("homeSeq", ""))
        self.device_type = str(device_info.get("deviceInfo", {}).get("deviceType", ""))
        self.client_id = client_id
        self.req = f'cmd/{self.device_type}/navilink-{self.mac_address}/'
        self.res = f'cmd/{self.device_type}/{self.home_seq}/{self.user_seq}/{self.client_id}/res/'
        self.mgpp = f'cmd/{self.device_type}/{self.home_seq}/{self.user_seq}/{self.client_id}/'

    def mgpp_default(self):
        return self.req + 'res'

    def mgpp_res_did(self):
        return self.mgpp + 'res/did'

    def mgpp_res(self):
        return self.mgpp + 'res'

    def mgpp_res_rsv_rd(self):
        return self.mgpp + 'res/rsv/rd'

    def mgpp_st_did(self):
        return self.req + 'st/did'

    def mgpp_st(self):
        return self.req + 'st'

    def mgpp_st_rsv_rd(self):
        return self.req + 'st/rsv/rd'

    def mgpp_control(self):
        """MGPP control topic - uses ctrl endpoint per spec"""
        return self.req + 'ctrl'

    def mgpp_ctrl_fail(self):
        """MGPP control failure topic per spec"""
        return self.req + 'ctrl-fail'

    def mgpp_connection(self):
        """MGPP device connection event topic per spec (legacy fallback)"""
        return f'evt/{self.device_type}/navilink-{self.mac_address}/connection'

    def mgpp_disconnect(self):
        """MGPP disconnect broadcast topic per spec"""
        return 'evt/+/mobile/event/disconnect-mqtt'

    def app_connection(self):
        return f'evt/{self.device_type}/navilink-{self.mac_address}/app-connection'


class Topics:
    """Topics for legacy protocol devices."""

    def __init__(self, user_info, device_info, client_id) -> None:
        self.user_seq = str(user_info.get("userInfo", {}).get("userSeq", ""))
        self.mac_address = device_info.get("deviceInfo", {}).get("macAddress", "")
        self.home_seq = str(device_info.get("deviceInfo", {}).get("homeSeq", ""))
        self.device_type = str(device_info.get("deviceInfo", {}).get("deviceType", ""))
        self.client_id = client_id
        self.req = f'cmd/{self.device_type}/navilink-{self.mac_address}/'
        self.res = f'cmd/{self.device_type}/{self.home_seq}/{self.user_seq}/{self.client_id}/res/'

    def start(self):
        return self.req + 'status/start'

    def channel_info_sub(self):
        return self.req + 'res/channelinfo'

    def channel_info_res(self):
        return self.res + 'channelinfo'

    def control_fail(self):
        return self.req + 'res/controlfail'

    def channel_status_sub(self):
        return self.req + 'res/channelstatus'

    def channel_status_req(self):
        return self.req + 'status/channelstatus'

    def channel_status_res(self):
        return self.res + 'channelstatus'

    def weekly_schedule_sub(self):
        return self.req + 'res/weeklyschedule'

    def weekly_schedule_req(self):
        return self.req + 'status/weeklyschedule'

    def weekly_schedule_res(self):
        return self.res + 'weeklyschedule'

    def simple_trend_sub(self):
        return self.req + 'res/simpletrend'

    def simple_trend_req(self):
        return self.req + 'status/simpletrend'

    def simple_trend_res(self):
        return self.res + 'simpletrend'

    def hourly_trend_sub(self):
        return self.req + 'res/hourlytrend'

    def hourly_trend_req(self):
        return self.req + 'status/hourlytrend'

    def hourly_trend_res(self):
        return self.res + 'hourlytrend'

    def daily_trend_sub(self):
        return self.req + 'res/dailytrend'

    def daily_trend_req(self):
        return self.req + 'status/dailytrend'

    def daily_trend_res(self):
        return self.res + 'dailytrend'

    def monthly_trend_sub(self):
        return self.req + 'res/monthlytrend'

    def monthly_trend_req(self):
        return self.req + 'status/monthlytrend'

    def monthly_trend_res(self):
        return self.res + 'monthlytrend'

    def control(self):
        return self.req + 'control'

    def connection(self):
        return self.req + 'connection'

    def disconnect(self):
        return 'evt/+/mobile/event/disconnect-mqtt'

    def app_connection(self):
        return f'evt/1/navilink-{self.mac_address}/app-connection'


class MgppMessages:

    def __init__(self, device_info, client_id, topics) -> None:
        self.mac_address = device_info.get("deviceInfo", {}).get("macAddress", "")
        self.device_type = int(device_info.get("deviceInfo", {}).get("deviceType", 1))
        self.additional_value = device_info.get("deviceInfo", {}).get("additionalValue", "")
        self.client_id = client_id
        self.topics = topics

    def mgpp_did(self):
        return {
            "clientID": self.client_id,
            "protocolVersion": 2,
            "request": {
                "additionalValue": self.additional_value,
                "command": 16777217,
                "deviceType": self.device_type,
                "macAddress": self.mac_address
            },
            "requestTopic": self.topics.mgpp_st_did(),
            "responseTopic": self.topics.mgpp_res_did(),
            "sessionID": ""
        }

    def mgpp_status(self):
        return {
            "clientID": self.client_id,
            "protocolVersion": 2,
            "request": {
                "additionalValue": self.additional_value,
                "command": 16777219,
                "deviceType": self.device_type,
                "macAddress": self.mac_address
            },
            "requestTopic": self.topics.mgpp_st(),
            "responseTopic": self.topics.mgpp_res(),
            "sessionID": ""
        }

    def mgpp_rsv_rd(self):
        return {
            "clientID": self.client_id,
            "protocolVersion": 2,
            "request": {
                "additionalValue": self.additional_value,
                "command": 16777222,
                "deviceType": self.device_type,
                "macAddress": self.mac_address
            },
            "requestTopic": self.topics.mgpp_st_rsv_rd(),
            "responseTopic": self.topics.mgpp_res_rsv_rd(),
            "sessionID": ""
        }

    def mgpp_power(self, state, channel_number):
        """MGPP power control message - uses RequestMgppControl structure per spec"""
        command_id = 33554434 if state else 33554433
        mode_str = "power-on" if state else "power-off"
        return {
            "clientID": self.client_id,
            "protocolVersion": 2,
            "request": {
                "additionalValue": self.additional_value,
                "command": command_id,
                "deviceType": self.device_type,
                "macAddress": self.mac_address,
                "mode": mode_str,
                "param": [],
                "paramStr": ""
            },
            "requestTopic": self.topics.mgpp_control(),
            "responseTopic": self.topics.mgpp_res(),
            "sessionID": ""
        }

    def mgpp_temperature(self, temp, channel_number):
        """MGPP temperature control message - uses RequestMgppControl structure per spec"""
        return {
            "clientID": self.client_id,
            "protocolVersion": 2,
            "request": {
                "additionalValue": self.additional_value,
                "command": 33554464,
                "deviceType": self.device_type,
                "macAddress": self.mac_address,
                "mode": "dhw-temperature",
                "param": [temp],
                "paramStr": ""
            },
            "requestTopic": self.topics.mgpp_control(),
            "responseTopic": self.topics.mgpp_res(),
            "sessionID": ""
        }

    def mgpp_operation_mode(self, mode, channel_number, days=None):
        """MGPP operation mode control message - uses RequestMgppControl structure per spec"""
        param = [mode]
        if mode == 5:
            vacation_days = days if days is not None else 7
            param = [mode, vacation_days]
        return {
            "clientID": self.client_id,
            "protocolVersion": 2,
            "request": {
                "additionalValue": self.additional_value,
                "command": 33554437,
                "deviceType": self.device_type,
                "macAddress": self.mac_address,
                "mode": "dhw-mode",
                "param": param,
                "paramStr": ""
            },
            "requestTopic": self.topics.mgpp_control(),
            "responseTopic": self.topics.mgpp_res(),
            "sessionID": ""
        }

    def mgpp_anti_legionella(self, state, channel_number):
        """MGPP anti-legionella control message - uses RequestMgppControl structure per spec"""
        command_id = 33554472 if state else 33554471
        mode_str = "anti-leg-on" if state else "anti-leg-off"
        param = [7] if state else []
        return {
            "clientID": self.client_id,
            "protocolVersion": 2,
            "request": {
                "additionalValue": self.additional_value,
                "command": command_id,
                "deviceType": self.device_type,
                "macAddress": self.mac_address,
                "mode": mode_str,
                "param": param,
                "paramStr": ""
            },
            "requestTopic": self.topics.mgpp_control(),
            "responseTopic": self.topics.mgpp_res(),
            "sessionID": ""
        }

    def mgpp_freeze_protection(self, state, channel_number):
        """MGPP freeze protection control message - uses RequestMgppControl structure per spec"""
        state_value = 2 if state else 1
        return {
            "clientID": self.client_id,
            "protocolVersion": 2,
            "request": {
                "additionalValue": self.additional_value,
                "command": 33554451,
                "deviceType": self.device_type,
                "macAddress": self.mac_address,
                "mode": "freeze-protection",
                "param": [],
                "paramStr": ""
            },
            "requestTopic": self.topics.mgpp_control(),
            "responseTopic": self.topics.mgpp_res(),
            "sessionID": ""
        }

    def mgpp_recirc_hot_button(self, state, channel_number):
        """MGPP recirculation hot button control message - uses RequestMgppControl structure per spec"""
        # Command ID 33554444, mode "recirc-hotbtn", param [state] where state is 2=ON, 1=OFF
        state_value = 2 if state else 1
        return {
            "clientID": self.client_id,
            "protocolVersion": 2,
            "request": {
                "additionalValue": self.additional_value,
                "command": 33554444,
                "deviceType": self.device_type,
                "macAddress": self.mac_address,
                "mode": "recirc-hotbtn",
                "param": [state_value],
                "paramStr": ""
            },
            "requestTopic": self.topics.mgpp_control(),
            "responseTopic": self.topics.mgpp_res(),
            "sessionID": ""
        }

    def last_will(self):
        """Last Will message - uses protocolVersion 1 per spec"""
        return {
            "clientID": self.client_id,
            "event": {
                "additionalValue": self.additional_value,
                "connection": {"os": "A", "status": 0},
                "deviceType": self.device_type,
                "macAddress": self.mac_address
            },
            "protocolVersion": 1,
            "requestTopic": self.topics.app_connection(),
            "sessionID": ""
        }


class Messages:

    def __init__(self, device_info, client_id, topics) -> None:
        self.mac_address = device_info.get("deviceInfo", {}).get("macAddress", "")
        self.device_type = int(device_info.get("deviceInfo", {}).get("deviceType", 1))
        self.additional_value = device_info.get("deviceInfo", {}).get("additionalValue", "")
        self.client_id = client_id
        self.topics = topics

    def channel_info(self):
        return {
            "clientID": self.client_id,
            "protocolVersion": 1,
            "request": {
                "additionalValue": self.additional_value,
                "command": 16777217,
                "deviceType": self.device_type,
                "macAddress": self.mac_address
            },
            "requestTopic": self.topics.start(),
            "responseTopic": self.topics.channel_info_res(),
            "sessionID": ""
        }

    def channel_status(self, channel_number, unit_count):
        return {
            "clientID": self.client_id,
            "protocolVersion": 1,
            "request": {
                "additionalValue": self.additional_value,
                "command": 16777220,
                "deviceType": self.device_type,
                "macAddress": self.mac_address,
                "status": {
                    "channelNumber": channel_number,
                    "unitNumberEnd": unit_count,
                    "unitNumberStart": 1
                }
            },
            "requestTopic": self.topics.channel_status_req(),
            "responseTopic": self.topics.channel_status_res(),
            "sessionID": ""
        }

    def power(self, state, channel_number):
        return {
            "clientID": self.client_id,
            "protocolVersion": 1,
            "request": {
                "additionalValue": self.additional_value,
                "command": 33554433,
                "control": {
                    "channelNumber": channel_number,
                    "mode": "power",
                    "param": [state]
                },
                "deviceType": self.device_type,
                "macAddress": self.mac_address
            },
            "requestTopic": self.topics.control(),
            "responseTopic": self.topics.channel_status_res(),
            "sessionID": ""
        }

    def hot_button(self, state, channel_number):
        return {
            "clientID": self.client_id,
            "protocolVersion": 1,
            "request": {
                "additionalValue": self.additional_value,
                "command": 33554437,
                "control": {
                    "channelNumber": channel_number,
                    "mode": "onDemand",
                    "param": [state]
                },
                "deviceType": self.device_type,
                "macAddress": self.mac_address
            },
            "requestTopic": self.topics.control(),
            "responseTopic": self.topics.channel_status_res(),
            "sessionID": ""
        }

    def temperature(self, temp, channel_number):
        return {
            "clientID": self.client_id,
            "protocolVersion": 1,
            "request": {
                "additionalValue": self.additional_value,
                "command": 33554435,
                "control": {
                    "channelNumber": channel_number,
                    "mode": "DHWTemperature",
                    "param": [temp]
                },
                "deviceType": self.device_type,
                "macAddress": self.mac_address
            },
            "requestTopic": self.topics.control(),
            "responseTopic": self.topics.channel_status_res(),
            "sessionID": ""
        }

    def last_will(self):
        return {
            "clientID": self.client_id,
            "event": {
                "additionalValue": self.additional_value,
                "connection": {"os": "A", "status": 0},
                "deviceType": self.device_type,
                "macAddress": self.mac_address
            },
            "protocolVersion": 1,
            "requestTopic": self.topics.app_connection(),
            "sessionID": ""
        }


class DeviceSorting(enum.Enum):
    NO_DEVICE = 0
    NPE = 1
    NCB = 2
    NHB = 3
    CAS_NPE = 4
    CAS_NHB = 5
    NFB = 6
    CAS_NFB = 7
    NFC = 8
    NPN = 9
    CAS_NPN = 10
    NPE2 = 11
    CAS_NPE2 = 12
    NCB_H = 13
    NVW = 14
    CAS_NVW = 15


class TemperatureType(enum.Enum):
    UNKNOWN = 0
    CELSIUS = 1
    FAHRENHEIT = 2


# Backwards compatibility aliases
NavilinkChannel = NavilinkDevice
MgppChannel = MgppDevice


class UnableToConnect(Exception):
    """Unable to connect to Navien Server Error"""


class UserNotFound(Exception):
    """Bad User Credentials Error"""


class NoNavienDevices(Exception):
    """No Navien Devices Found Error"""


class NoNetworkConnection(Exception):
    """Network is unavailable"""


class NoResponseData(Exception):
    """No Data in Response"""


class PollingError(Exception):
    """Error during polling"""


class DisconnectEvent(Exception):
    """Server disconnected"""


class StaleConnectionError(Exception):
    """Connection is stale - no data received"""


class NoChannelInformation(Exception):
    """No Channel Information"""


class NoAccessKey(Exception):
    """Access key, Secret key, or Session token missing"""
