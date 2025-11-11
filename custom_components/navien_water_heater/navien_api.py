import asyncio
import enum
import json
import logging
import uuid
from datetime import datetime,timedelta
import AWSIoTPythonSDK.MQTTLib as mqtt
import aiohttp

_LOGGER = logging.getLogger(__name__)

class NavilinkConnect():

    # The Navien server.
    navienWebServer = "https://nlus.naviensmartcontrol.com/api/v2"

    def __init__(self, userId, passwd, polling_interval = 15, aws_cert_path = "AmazonRootCA1.pem", subscribe_all_topics=False):
        """
        Construct a new 'NavilinkConnect' object.

        :param userId: The user ID used to log in to the mobile application
        :param passwd: The corresponding user's password
        :return: returns nothing
        """
        _LOGGER.debug("Initializing NaviLink connection")
        self.userId = userId
        self.passwd = passwd
        self.polling_interval = polling_interval
        self.aws_cert_path = aws_cert_path
        self.subscribe_all_topics = subscribe_all_topics
        self.loop = asyncio.get_running_loop()
        self.connected = False
        self.shutting_down = False
        self.user_info = None
        self.device_info_list = []  # List of all discovered devices
        self.device_info_by_mac = {}  # Dict keyed by MAC address for quick lookup
        self.client = None
        self.client_id = ""
        self.topics_by_device = {}  # Dict of Topics objects keyed by MAC address
        self.messages_by_device = {}  # Dict of Messages objects keyed by MAC address
        self.devices = {}  # Dict of device/channel objects keyed by (mac_address, channel_number) tuple
        self.monitored_devices = set()  # Set of MAC addresses being monitored
        self.disconnect_event = asyncio.Event()
        self.channel_info_event = None
        self.response_events = {}
        self.client_lock = asyncio.Lock()
        self.last_poll = None

    def is_mgpp_device(self, mac_address: str) -> bool:
        """Check if a device with the given MAC address uses MGPP protocol."""
        device_info = self.device_info_by_mac.get(mac_address)
        if device_info:
            return self._uses_mgpp_protocol(device_info)
        return False

    def _uses_mgpp_protocol(self, device_info):
        """
        Determine if the device uses the MGPP protocol.
        
        Currently, only device type 52 (NWP500) uses MGPP protocol.
        This function can be extended to support other device types in the future.
        
        :param device_info: Device info dict to check
        :return: True if device uses MGPP protocol, False otherwise
        """
        device_type = int(device_info.get("deviceInfo",{}).get("deviceType",1))
        return device_type == 52

    async def start(self):
        """Login and discover all devices. Does not connect to MQTT."""
        return await self.login()

    async def _start(self):
        if not self.shutting_down:
            tasks = [
                asyncio.create_task(self._poll_mqtt_server(), name = "Poll MQTT Server"),
                asyncio.create_task(self._server_connection_lost(), name = "Connection Lost Event"),
                asyncio.create_task(self._refresh_connection(), name = "Reresh Connection")
            ]
            done, pending = await asyncio.wait(tasks,return_when=asyncio.FIRST_EXCEPTION)
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
                await asyncio.sleep(15)
                asyncio.create_task(self.start())

    async def login(self):
        """
        Login to the REST API and save user information
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(NavilinkConnect.navienWebServer + "/user/sign-in", json={"userId": self.userId, "password": self.passwd}) as response:
                # If an error occurs this will raise it, otherwise it calls get_device and returns after device is obtained from the server
                if response.status != 200:
                    raise UnableToConnect("Unexpected response during login")
                response_data = await response.json()
                if response_data.get('msg','') == "USER_NOT_FOUND":
                    raise UserNotFound("Unable to log in with given credentials")
                try:
                    response_data["data"]
                    self.user_info = response_data["data"]
                except:
                    raise NoResponseData("Unexpected problem while retrieving user data")
                
                return await self._get_device_list()

    async def _get_device_list(self):
        """
        Get list of devices for the given user credentials
        """
        headers = {"Authorization":self.user_info.get("token",{}).get("accessToken","")}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(NavilinkConnect.navienWebServer + "/device/list", json={"offset":0,"count":20,"userId":self.userId}) as response:
                # If an error occurs this will raise it, otherwise it returns the gateway list.
                if response.status != 200:
                    raise UnableToConnect("Unexpected response while retrieving device list")
                response_data = await response.json()
                try:
                    response_data["data"]
                    device_info_list = response_data["data"]
                    self.device_info_list = device_info_list
                    # Build lookup dict by MAC address
                    for device_info in device_info_list:
                        mac = device_info.get("deviceInfo",{}).get("macAddress","")
                        if mac:
                            self.device_info_by_mac[mac] = device_info
                    _LOGGER.debug(f"Discovered {len(device_info_list)} devices")
                except:
                    raise NoResponseData("Unexpected problem while retrieving device list")
                
                return device_info_list

    async def connect_and_subscribe_devices(self, mac_addresses: list[str]):
        """
        Connect to AWS MQTT and subscribe to topics for the specified devices.
        
        :param mac_addresses: List of MAC addresses to monitor
        """
        if not mac_addresses:
            raise ValueError("At least one device MAC address must be provided")
        
        self.monitored_devices = set(mac_addresses)
        self.client_id = str(uuid.uuid4())
        
        accessKeyId = self.user_info.get("token",{}).get("accessKeyId",None)
        secretKey = self.user_info.get("token",{}).get("secretKey",None)
        sessionToken = self.user_info.get("token",{}).get("sessionToken",None)

        if not (accessKeyId and secretKey and sessionToken):
            raise NoAccessKey("Missing Access key, Secret key, or Session token")
        
        # Initialize Topics and Messages objects for each monitored device
        for mac in mac_addresses:
            device_info = self.device_info_by_mac.get(mac)
            if not device_info:
                _LOGGER.warning(f"Device with MAC {mac} not found in discovered devices")
                continue
            
            if self._uses_mgpp_protocol(device_info):
                self.topics_by_device[mac] = MgppTopics(self.user_info, device_info, self.client_id)
                self.messages_by_device[mac] = MgppMessages(device_info, self.client_id, self.topics_by_device[mac])
            else:
                self.topics_by_device[mac] = Topics(self.user_info, device_info, self.client_id)
                self.messages_by_device[mac] = Messages(device_info, self.client_id, self.topics_by_device[mac])
        
        # Connect to MQTT (single connection for all devices)
        self.client = mqtt.AWSIoTMQTTClient(clientID = self.client_id, protocolType=4, useWebsocket=True, cleanSession=True)
        self.client.configureEndpoint(hostName= 'a1t30mldyslmuq-ats.iot.us-east-1.amazonaws.com', portNumber= 443)
        self.client.configureUsernamePassword(username='?SDK=Android&Version=2.16.12', password=None)
        
        # Use first device's last will (or could combine multiple)
        if self.topics_by_device:
            first_mac = list(self.topics_by_device.keys())[0]
            first_device_info = self.device_info_by_mac[first_mac]
            if self._uses_mgpp_protocol(first_device_info):
                topics = self.topics_by_device[first_mac]
                messages = self.messages_by_device[first_mac]
            else:
                topics = self.topics_by_device[first_mac]
                messages = self.messages_by_device[first_mac]
            self.client.configureLastWill(topic = topics.app_connection(), payload = json.dumps(messages.last_will(),separators=(',',':')), QoS=1, retain=False)
        
        await self.loop.run_in_executor(None,self.client.configureCredentials,self.aws_cert_path)
        self.client.configureIAMCredentials(AWSAccessKeyID=accessKeyId, AWSSecretAccessKey=secretKey, AWSSessionToken=sessionToken)
        self.client.configureConnectDisconnectTimeout(5)
        self.client.onOffline=self._on_offline
        self.client.onOnline=self._on_online
        await self.loop.run_in_executor(None,self.client.connect)
        
        # Subscribe to topics for each monitored device
        for mac in mac_addresses:
            await self._subscribe_to_device_topics(mac)
        
        # Initialize device info for each monitored device
        for mac in mac_addresses:
            device_info = self.device_info_by_mac.get(mac)
            if not device_info:
                continue
            if self._uses_mgpp_protocol(device_info):
                await self._get_mgpp_device_info(mac, device_info)
            else:
                await self._get_channel_info(mac, device_info)
        
        # Start polling task if polling interval is set
        if self.polling_interval > 0:
            asyncio.create_task(self._start())
        
        # Get initial status for all devices
        await self._get_channel_status_all(wait_for_response = True)
        self.last_poll = datetime.now()

    async def _poll_mqtt_server(self):
        time_delta = 0
        while self.connected and not self.shutting_down:
            if time_delta < self.polling_interval:
                interval = self.polling_interval - time_delta
            else:
                interval = 0.1
            await asyncio.sleep(interval)
            pre_poll = datetime.now()
            if not self.client_lock.locked():
                await self._get_channel_status_all()
                # Debug: Show device status after polling
                for device_key, device in self.devices.items():
                    _LOGGER.debug(f"Device {device_key} status after polling: {device.channel_status}")
            self.last_poll = datetime.now()
            time_delta = (self.last_poll - pre_poll).total_seconds()
        if not self.shutting_down:
            raise PollingError("Polling of AWS IOT Navilink server completed")

    async def _server_connection_lost(self):
        await self.disconnect_event.wait()
        self.disconnect_event.clear()
        raise DisconnectEvent("Disconnected from Navilink server...")

    async def _refresh_connection(self):
        now = datetime.now()
        target_time = datetime(now.year, now.month, now.day, 2, 0, 0)
        if now > target_time:
            # If it's already past 2 am, wait until tomorrow
            target_time += timedelta(days=1)
        delta = (target_time - now).total_seconds()
        await asyncio.sleep(delta)
        await self.disconnect(shutting_down=False)

    async def disconnect(self,shutting_down=True):
        if self.client and self.connected:
            self.shutting_down = shutting_down
            try:
                await self.loop.run_in_executor(None,self.client.disconnect)
            except Exception as e:
                _LOGGER.warning(f"Error during disconnect: {e}")
                # Continue with shutdown even if disconnect fails

    def _on_online(self):
        self.connected = True

    def _on_offline(self):
        if not self.shutting_down:
            self.disconnect_event.set()

    async def async_subscribe(self,topic,QoS=1,callback=None):
        _LOGGER.debug("Subscribing to " + topic)
        try:
            def subscribe():
                self.client.subscribe(topic=topic,QoS=QoS,callback=callback)

            async with self.client_lock:
                await self.loop.run_in_executor(None,subscribe)
        except Exception as e:
            _LOGGER.debug("Error occurred in async_subscribe: " + str(e))
            await self.disconnect(shutting_down=False)           

    async def async_publish(self,topic,payload,QoS=1,session_id=""):
        try:
            def publish():
                self.client.publish(topic=topic,payload=json.dumps(payload,separators=(',',':')),QoS=QoS)
                                
            async with self.client_lock:
                await self.loop.run_in_executor(None,publish)

            if response_event :=  self.response_events.get(session_id,None):
                try:
                    await asyncio.wait_for(response_event.wait(),timeout=self.polling_interval)
                except:
                    pass
                response_event.clear()
                self.response_events.pop(session_id)
        except Exception as e:
            _LOGGER.debug("Error occurred in async_publish: " + str(e))
            if response_event :=  self.response_events.get(session_id,None):
                response_event.clear()
                self.response_events.pop(session_id)
            await self.disconnect(shutting_down=False)   


    async def _subscribe_to_device_topics(self, mac_address: str):
        """Subscribe to MQTT topics for a specific device."""
        device_info = self.device_info_by_mac.get(mac_address)
        if not device_info:
            return
        
        topics = self.topics_by_device.get(mac_address)
        if not topics:
            return
        
        if self._uses_mgpp_protocol(device_info):
            # MGPP protocol devices (currently NWP500 aka deviceType 52)
            await self.async_subscribe(topic=topics.mgpp_default(), callback=self.handle_other)
            await self.async_subscribe(topic=topics.mgpp_res_did(), callback=self.handle_mgpp_did)
            await self.async_subscribe(topic=topics.mgpp_res(), callback=self.handle_mgpp_status)
            await self.async_subscribe(topic=topics.mgpp_res_rsv_rd(), callback=self.handle_mgpp_rsv)
            # Subscribe to control failure notifications per spec
            await self.async_subscribe(topic=topics.mgpp_ctrl_fail(), callback=self.handle_mgpp_ctrl_fail)
            # Subscribe to connection event topics per spec
            await self.async_subscribe(topic=topics.app_connection(), callback=self.handle_mgpp_connection)
            await self.async_subscribe(topic=topics.mgpp_connection(), callback=self.handle_mgpp_connection)
            # Subscribe to disconnect broadcast per spec
            await self.async_subscribe(topic=topics.mgpp_disconnect(), callback=self.handle_mgpp_disconnect)
        else:
            await self.async_subscribe(topic=topics.channel_info_sub(),callback=self.handle_other)
            await self.async_subscribe(topic=topics.channel_info_res(),callback=self.handle_channel_info)
            await self.async_subscribe(topic=topics.control_fail(),callback=self.handle_other)
            await self.async_subscribe(topic=topics.channel_status_sub(),callback=self.handle_other)
            await self.async_subscribe(topic=topics.channel_status_res(),callback=self.handle_channel_status)
            await self.async_subscribe(topic=topics.connection(),callback=self.handle_other)
            await self.async_subscribe(topic=topics.disconnect(),callback=self.handle_other)
            await self.async_subscribe(topic=topics.disconnect(),callback=self.handle_other)
            if self.subscribe_all_topics:
                await self.async_subscribe(topic=topics.weekly_schedule_sub(),callback=self.handle_other)
                await self.async_subscribe(topic=topics.weekly_schedule_res(),callback=self.handle_weekly_schedule)
                await self.async_subscribe(topic=topics.simple_trend_sub(),callback=self.handle_other)
                await self.async_subscribe(topic=topics.simple_trend_res(),callback=self.handle_simple_trend)
                await self.async_subscribe(topic=topics.hourly_trend_sub(),callback=self.handle_other)
                await self.async_subscribe(topic=topics.hourly_trend_res(),callback=self.handle_hourly_trend)
                await self.async_subscribe(topic=topics.daily_trend_sub(),callback=self.handle_other)
                await self.async_subscribe(topic=topics.daily_trend_res(),callback=self.handle_daily_trend)
                await self.async_subscribe(topic=topics.monthly_trend_sub(),callback=self.handle_other)
                await self.async_subscribe(topic=topics.monthly_trend_res(),callback=self.handle_monthly_trend)

    async def _get_mgpp_device_info(self, mac_address: str, device_info: dict):
        """Initialize MGPP device by requesting DID and status information"""
        _LOGGER.debug(f"Initializing MGPP device {mac_address}...")
        
        device_key = (mac_address, 1)  # MGPP devices use channel 1
        
        # Create MGPP channel if it doesn't exist
        if device_key not in self.devices:
            # Create a basic channel with minimal info for MGPP
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
            self.devices[device_key] = MgppChannel(1, channel_info, self, device_info, None)
            _LOGGER.debug(f"Created MGPP channel for device {mac_address}")
        
        topics = self.topics_by_device.get(mac_address)
        messages = self.messages_by_device.get(mac_address)
        if not topics or not messages:
            raise ValueError(f"Topics/Messages not initialized for device {mac_address}")
        
        # Request device ID
        topic = topics.mgpp_st_did()
        payload = messages.mgpp_did()
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        
        # Request status
        topic = topics.mgpp_st()
        payload = messages.mgpp_status()
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        
        # Request RSV data
        topic = topics.mgpp_st_rsv_rd()
        payload = messages.mgpp_rsv_rd()
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        
        if device_key not in self.devices:
            raise NoChannelInformation(f"Unable to get MGPP device information for {mac_address}")

    async def _get_channel_info(self, mac_address: str, device_info: dict):
        """Get channel information for a legacy protocol device."""
        topics = self.topics_by_device.get(mac_address)
        messages = self.messages_by_device.get(mac_address)
        if not topics or not messages:
            raise ValueError(f"Topics/Messages not initialized for device {mac_address}")
        
        topic = topics.start()
        payload = messages.channel_info()
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic,payload=payload,session_id=session_id)
        
        # Check if channels were created (handled in async_handle_channel_info)
        device_channels = [key for key in self.devices.keys() if key[0] == mac_address]
        if len(device_channels) == 0:
            raise NoChannelInformation(f"Unable to get channel information for device {mac_address}")

    async def _get_channel_status_all(self,wait_for_response=False):
        """Get status for all monitored devices."""
        # Group devices by MAC address
        devices_by_mac = {}
        for device_key, device in self.devices.items():
            mac_address = device_key[0]
            if mac_address not in self.monitored_devices:
                continue
            if mac_address not in devices_by_mac:
                devices_by_mac[mac_address] = []
            devices_by_mac[mac_address].append(device)
        
        # Poll each monitored device
        for mac_address, device_list in devices_by_mac.items():
            device_info = self.device_info_by_mac.get(mac_address)
            if not device_info:
                continue
            
            if self._uses_mgpp_protocol(device_info):
                # MGPP protocol - request status and RSV data
                _LOGGER.debug(f"Using MGPP protocol for status requests for device {mac_address}")
                await self._get_mgpp_status_all(mac_address, wait_for_response)
            else:
                # Legacy protocol
                _LOGGER.debug(f"Using legacy protocol for status requests for device {mac_address}")
                topics = self.topics_by_device.get(mac_address)
                messages = self.messages_by_device.get(mac_address)
                if not topics or not messages:
                    continue
                for device in device_list:
                    topic = topics.channel_status_req()
                    payload = messages.channel_status(device.channel_number, device.channel_info.get("unitCount",1))
                    session_id = self.get_session_id()
                    payload["sessionID"] = session_id
                    if wait_for_response:
                        self.response_events[session_id] = asyncio.Event()
                    else:
                        session_id = ""
                    await self.async_publish(topic=topic,payload=payload,session_id=session_id)

    async def _get_mgpp_status_all(self, mac_address: str, wait_for_response=False):
        """Poll MGPP device for status and RSV data"""
        _LOGGER.debug(f"Polling MGPP device {mac_address} for status...")
        topics = self.topics_by_device.get(mac_address)
        messages = self.messages_by_device.get(mac_address)
        if not topics or not messages:
            return
        
        # Request status
        topic = topics.mgpp_st()
        payload = messages.mgpp_status()
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        _LOGGER.debug(f"Publishing status request to {topic} with session {session_id}")
        if wait_for_response:
            self.response_events[session_id] = asyncio.Event()
        else:
            session_id = ""
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        
        # Request RSV data
        topic = topics.mgpp_st_rsv_rd()
        payload = messages.mgpp_rsv_rd()
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        if wait_for_response:
            self.response_events[session_id] = asyncio.Event()
        else:
            session_id = ""
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        

    async def _get_channel_status(self, mac_address: str, channel_number: int):
        """Get status for a specific channel."""
        device_key = (mac_address, channel_number)
        device = self.devices.get(device_key)
        if not device:
            return
        
        topics = self.topics_by_device.get(mac_address)
        messages = self.messages_by_device.get(mac_address)
        if not topics or not messages:
            return
        
        topic = topics.channel_status_req()
        payload = messages.channel_status(device.channel_number, device.channel_info.get("unitCount",1))
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic,payload=payload,session_id=session_id)

    async def _power_command(self, mac_address: str, state, channel_number):
        """Unified power control command that routes to appropriate protocol implementation"""
        device_info = self.device_info_by_mac.get(mac_address)
        if device_info and self._uses_mgpp_protocol(device_info):
            await self._mgpp_power_command(mac_address, state, channel_number)
        else:
            await self._legacy_power_command(mac_address, state, channel_number)

    async def _legacy_power_command(self, mac_address: str, state, channel_number):
        """Legacy protocol power control command"""
        topics = self.topics_by_device.get(mac_address)
        messages = self.messages_by_device.get(mac_address)
        if not topics or not messages:
            return
        state_num = 2
        if state:
            state_num = 1
        topic = topics.control()
        payload = messages.power(state_num, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic,payload=payload,session_id=session_id)
        await self._get_channel_status(mac_address, channel_number)

    async def _mgpp_power_command(self, mac_address: str, state, channel_number):
        """MGPP power control command"""
        topics = self.topics_by_device.get(mac_address)
        messages = self.messages_by_device.get(mac_address)
        if not topics or not messages:
            return
        
        topic = topics.mgpp_control()
        payload = messages.mgpp_power(state, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        # Request status update after control command
        await self._get_mgpp_status_all(mac_address, wait_for_response=True)

    async def _hot_button_command(self, mac_address: str, state, channel_number):
        """Hot button control command"""
        topics = self.topics_by_device.get(mac_address)
        messages = self.messages_by_device.get(mac_address)
        if not topics or not messages:
            return
        state_num = 2
        if state:
            state_num = 1
        topic = topics.control()
        payload = messages.hot_button(state_num, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic,payload=payload,session_id=session_id)
        await self._get_channel_status(mac_address, channel_number)

    async def _temperature_command(self, mac_address: str, temp, channel_number):
        """Unified temperature control command that routes to appropriate protocol implementation"""
        device_info = self.device_info_by_mac.get(mac_address)
        if device_info and self._uses_mgpp_protocol(device_info):
            await self._mgpp_temperature_command(mac_address, temp, channel_number)
        else:
            await self._legacy_temperature_command(mac_address, temp, channel_number)

    async def _legacy_temperature_command(self, mac_address: str, temp, channel_number):
        """Legacy protocol temperature control command"""
        topics = self.topics_by_device.get(mac_address)
        messages = self.messages_by_device.get(mac_address)
        if not topics or not messages:
            return
        topic = topics.control()
        payload = messages.temperature(temp, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic,payload=payload,session_id=session_id)
        await self._get_channel_status(mac_address, channel_number)

    async def _mgpp_temperature_command(self, mac_address: str, temp, channel_number):
        """MGPP temperature control command"""
        topics = self.topics_by_device.get(mac_address)
        messages = self.messages_by_device.get(mac_address)
        if not topics or not messages:
            return
        
        topic = topics.mgpp_control()
        payload = messages.mgpp_temperature(temp, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        # Request status update after control command
        await self._get_mgpp_status_all(mac_address, wait_for_response=True)

    async def _mgpp_operation_mode_command(self, mac_address: str, mode, channel_number):
        """MGPP operation mode control command"""
        topics = self.topics_by_device.get(mac_address)
        messages = self.messages_by_device.get(mac_address)
        if not topics or not messages:
            return
        
        topic = topics.mgpp_control()
        payload = messages.mgpp_operation_mode(mode, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        await self._get_mgpp_status_all(mac_address, wait_for_response=True)

    async def _mgpp_anti_legionella_command(self, mac_address: str, state, channel_number):
        """MGPP anti-legionella control command"""
        topics = self.topics_by_device.get(mac_address)
        messages = self.messages_by_device.get(mac_address)
        if not topics or not messages:
            return
        
        topic = topics.mgpp_control()
        payload = messages.mgpp_anti_legionella(state, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        await self._get_mgpp_status_all(mac_address, wait_for_response=True)

    async def _mgpp_freeze_protection_command(self, mac_address: str, state, channel_number):
        """MGPP freeze protection control command"""
        topics = self.topics_by_device.get(mac_address)
        messages = self.messages_by_device.get(mac_address)
        if not topics or not messages:
            return
        
        topic = topics.mgpp_control()
        payload = messages.mgpp_freeze_protection(state, channel_number)
        session_id = self.get_session_id()
        payload["sessionID"] = session_id
        self.response_events[session_id] = asyncio.Event()
        await self.async_publish(topic=topic, payload=payload, session_id=session_id)
        await self._get_mgpp_status_all(mac_address, wait_for_response=True)

    def get_session_id(self):
        return str(int(round((datetime.utcnow() - datetime(1970, 1, 1)).total_seconds()*1000)))

    def async_handle_channel_info(self, client, userdata, message):
        response = json.loads(message.payload)
        print(response)
        channel_info = response.get("response",{})
        session_id = response.get("sessionID","unknown")
        
        # Extract MAC address from the request (it's in the topic or we need to match by device)
        # For now, we'll match by finding which device this response belongs to
        # The MAC address should be in the device_info we stored
        mac_address = None
        for mac, device_info in self.device_info_by_mac.items():
            # Check if this response matches this device (could check topic or other fields)
            # For legacy protocol, we'll create channels for the first monitored device that doesn't have channels yet
            if mac in self.monitored_devices:
                device_key = (mac, 0)  # Check if we have any channels for this device
                existing_channels = [key for key in self.devices.keys() if key[0] == mac]
                if len(existing_channels) == 0:
                    mac_address = mac
                    break
        
        if mac_address:
            device_info = self.device_info_by_mac.get(mac_address)
            self.devices.update({
                (mac_address, channel.get("channelNumber",0)): NavilinkChannel(
                    channel.get("channelNumber",0),
                    channel.get("channel",{}),
                    self,
                    device_info
                ) for channel in channel_info.get("channelInfo",{}).get("channelList",[])
            })
        
        if response_event := self.response_events.get(session_id,None):
            response_event.set()

    def handle_channel_info(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_channel_info, client, userdata, message)

    def async_handle_channel_status(self, client, userdata, message):
        response = json.loads(message.payload)
        channel_status = response.get("response",{}).get("channelStatus",{})
        session_id = response.get("sessionID","unknown")
        channel_number = channel_status.get("channelNumber",0)
        
        # Find the device that matches this channel status
        # We need to match by MAC address - it should be in the response or we match by channel number
        # For legacy protocol, match by finding device with matching channel
        for device_key, device in self.devices.items():
            mac_address, ch_num = device_key
            if ch_num == channel_number and mac_address in self.monitored_devices:
                device.update_channel_status(channel_status.get("channel",{}))
                break
        
        if response_event := self.response_events.get(session_id,None):
            response_event.set()

    def handle_channel_status(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_channel_status, client, userdata, message)

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
        session_id = response.get("sessionID", "unknown")
        
        # Extract MAC address from response
        mac_address = response.get("response", {}).get("macAddress", "")
        if not mac_address:
            # Try to find by matching device
            for mac in self.monitored_devices:
                device_info = self.device_info_by_mac.get(mac)
                if device_info and self._uses_mgpp_protocol(device_info):
                    mac_address = mac
                    break
        
        # Store DID feature data in the channel for temperature conversion reference
        if mac_address:
            device_key = (mac_address, 1)  # MGPP uses channel 1
            if device_key in self.devices:
                channel = self.devices[device_key]
                if hasattr(channel, 'did_features'):
                    feature_data = response.get("response", {}).get("feature", {})
                    channel.did_features = feature_data
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
        session_id = response.get("sessionID", "unknown")
        if response_event := self.response_events.get(session_id, None):
            response_event.set()
            _LOGGER.debug(f"Set response event for session ID: {session_id}")
        else:
            _LOGGER.debug(f"No response event found for session ID: {session_id}")
        
        # Extract MAC address from response
        mac_address = response.get("response", {}).get("macAddress", "")
        if not mac_address:
            # Try to find by matching device
            for mac in self.monitored_devices:
                device_info = self.device_info_by_mac.get(mac)
                if device_info and self._uses_mgpp_protocol(device_info):
                    mac_address = mac
                    break
        
        # Update channel if it exists
        if mac_address:
            device_key = (mac_address, 1)  # MGPP uses channel 1
            if device_key in self.devices:
                channel = self.devices[device_key]
                if hasattr(channel, 'update_channel_status'):
                    _LOGGER.debug(f"Updating channel {channel.channel_number} with status response")
                    channel.update_channel_status('status', response)
                else:
                    _LOGGER.debug(f"Channel {channel.channel_number} does not have update_channel_status method")

    def handle_mgpp_status(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_mgpp_status, client, userdata, message)

    def async_handle_mgpp_rsv(self, client, userdata, message):
        response = json.loads(message.payload)
        _LOGGER.debug("MGPP RSV Response: " + json.dumps(response, indent=2))
        session_id = response.get("sessionID", "unknown")
        if response_event := self.response_events.get(session_id, None):
            response_event.set()
        else:
            _LOGGER.debug(f"No response event found for session ID: {session_id}")
        
        # Extract MAC address from response
        mac_address = response.get("response", {}).get("macAddress", "")
        if not mac_address:
            # Try to find by matching device
            for mac in self.monitored_devices:
                device_info = self.device_info_by_mac.get(mac)
                if device_info and self._uses_mgpp_protocol(device_info):
                    mac_address = mac
                    break
        
        # Update channel if it exists
        if mac_address:
            device_key = (mac_address, 1)  # MGPP uses channel 1
            if device_key in self.devices:
                channel = self.devices[device_key]
                if hasattr(channel, 'update_channel_status'):
                    channel.update_channel_status('rsv', response)

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
        # Check if status indicates disconnect (status <= 0)
        event_data = response.get("event", {})
        connection = event_data.get("connection", {})
        status = connection.get("status", 0)
        if status <= 0:
            _LOGGER.warning("Device connection status indicates disconnect (status <= 0)")
            # Could trigger disconnect handling here if needed

    def handle_mgpp_connection(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_mgpp_connection, client, userdata, message)

    def async_handle_mgpp_disconnect(self, client, userdata, message):
        """Handle MGPP disconnect broadcast per spec"""
        _LOGGER.warning("MGPP Disconnect Broadcast received - device MQTT session dropped")
        # The spec indicates receipt alone triggers action - could force reconnection here

    def handle_mgpp_disconnect(self, client, userdata, message):
        self.loop.call_soon_threadsafe(self.async_handle_mgpp_disconnect, client, userdata, message)

    def handle_other(self, client, userdata, message):
        _LOGGER.info(message.payload.decode('utf-8') + '\n')

class NavilinkChannel:

    def __init__(self, channel_number, channel_info, hub, device_info) -> None:
        self.channel_number = channel_number
        self.channel_info = self.convert_channel_info(channel_info)
        self.hub = hub
        self.device_info = device_info
        self.mac_address = device_info.get("deviceInfo",{}).get("macAddress","") if device_info else ""
        self.callbacks = []
        self.channel_status = {}
        self.unit_list = {}
        self.waiting_for_response = False

    def register_callback(self,callback):
        self.callbacks.append(callback)

    def deregister_callback(self,callback):
        if self.callbacks:
            self.callbacks.pop(self.callbacks.index(callback))

    def update_channel_status(self,channel_status):
        self.channel_status = self.convert_channel_status(channel_status)
        if not self.waiting_for_response:
            self.publish_update()

    def publish_update(self):
        if len(self.callbacks) > 0:
            # Schedule callbacks on the main event loop to avoid threading issues
            for callback in self.callbacks:
                self.hub.loop.call_soon_threadsafe(callback)

    async def set_power_state(self,state):
        if not self.waiting_for_response:
            self.waiting_for_response = True
            await self.hub._power_command(self.mac_address, state, self.channel_number)
            self.publish_update()
            self.waiting_for_response = False

    async def set_hot_button_state(self,state):
        if not self.waiting_for_response:
            self.waiting_for_response = True
            await self.hub._hot_button_command(self.mac_address, state, self.channel_number)
            self.publish_update()
            self.waiting_for_response = False

    async def set_temperature(self,temp):
        if not self.waiting_for_response:
            self.waiting_for_response = True
            await self.hub._temperature_command(self.mac_address, temp, self.channel_number)
            self.publish_update()
            self.waiting_for_response = False

    def convert_channel_status(self,channel_status):
        channel_status["powerStatus"] = channel_status["powerStatus"] == 1
        channel_status["onDemandUseFlag"] = channel_status["onDemandUseFlag"] == 1
        channel_status["avgCalorie"] = channel_status["avgCalorie"]/2.0
        if self.channel_info.get("temperatureType",2) == TemperatureType.CELSIUS.value:
            if channel_status["unitType"] in [DeviceSorting.NFC.value,DeviceSorting.NCB_H.value,DeviceSorting.NFB.value,DeviceSorting.NVW.value,]:
                GIUFactor = 100
            else:
                GIUFactor = 10

            if channel_status["unitType"] in [
                DeviceSorting.NPE.value,
                DeviceSorting.NPN.value,
                DeviceSorting.NPE2.value,
                DeviceSorting.NCB.value,
                DeviceSorting.NFC.value,
                DeviceSorting.NCB_H.value,
                DeviceSorting.CAS_NPE.value,
                DeviceSorting.CAS_NPN.value,
                DeviceSorting.CAS_NPE2.value,
                DeviceSorting.NFB.value,
                DeviceSorting.NVW.value,
                DeviceSorting.CAS_NFB.value,
                DeviceSorting.CAS_NVW.value,
            ]:
                channel_status["DHWSettingTemp"] = round(channel_status["DHWSettingTemp"] / 2.0, 1)
                channel_status["avgInletTemp"] = round(channel_status["avgInletTemp"] / 2.0, 1)
                channel_status["avgOutletTemp"] = round(channel_status["avgOutletTemp"] / 2.0, 1)            
                for i in range(channel_status.get("unitCount",0)):
                    channel_status["unitInfo"]["unitStatusList"][i]["gasInstantUsage"] = round((channel_status["unitInfo"]["unitStatusList"][i]["gasInstantUsage"] * GIUFactor)/ 10.0, 1)
                    channel_status["unitInfo"]["unitStatusList"][i]["accumulatedGasUsage"] = round(channel_status["unitInfo"]["unitStatusList"][i]["accumulatedGasUsage"] / 10.0, 1)
                    channel_status["unitInfo"]["unitStatusList"][i]["DHWFlowRate"] = round(channel_status["unitInfo"]["unitStatusList"][i]["DHWFlowRate"] / 10.0, 1)
                    channel_status["unitInfo"]["unitStatusList"][i]["currentOutletTemp"] = round(channel_status["unitInfo"]["unitStatusList"][i]["currentOutletTemp"] / 2.0, 1)
                    channel_status["unitInfo"]["unitStatusList"][i]["currentInletTemp"] = round(channel_status["unitInfo"]["unitStatusList"][i]["currentInletTemp"] / 2.0, 1)
        elif self.channel_info.get("temperatureType",2) == TemperatureType.FAHRENHEIT.value:
            if channel_status["unitType"] in [DeviceSorting.NFC.value,DeviceSorting.NCB_H.value,DeviceSorting.NFB.value,DeviceSorting.NVW.value,]:
                GIUFactor = 10
            else:
                GIUFactor = 1

            if channel_status["unitType"] in [
                DeviceSorting.NPE.value,
                DeviceSorting.NPN.value,
                DeviceSorting.NPE2.value,
                DeviceSorting.NCB.value,
                DeviceSorting.NFC.value,
                DeviceSorting.NCB_H.value,
                DeviceSorting.CAS_NPE.value,
                DeviceSorting.CAS_NPN.value,
                DeviceSorting.CAS_NPE2.value,
                DeviceSorting.NFB.value,
                DeviceSorting.NVW.value,
                DeviceSorting.CAS_NFB.value,
                DeviceSorting.CAS_NVW.value,
            ]:
                for i in range(channel_status.get("unitCount",0)):
                    channel_status["unitInfo"]["unitStatusList"][i]["gasInstantUsage"] = round(channel_status["unitInfo"]["unitStatusList"][i]["gasInstantUsage"] * GIUFactor * 3.968, 1)
                    channel_status["unitInfo"]["unitStatusList"][i]["accumulatedGasUsage"] = round(channel_status["unitInfo"]["unitStatusList"][i]["accumulatedGasUsage"] * 35.314667 / 10.0, 1)
                    channel_status["unitInfo"]["unitStatusList"][i]["DHWFlowRate"] = round(channel_status["unitInfo"]["unitStatusList"][i]["DHWFlowRate"] / 37.85, 1)

        return channel_status

    def convert_channel_info(self,channel_info):
        if channel_info.get("temperatureType",2) == TemperatureType.CELSIUS.value:
            channel_info["setupDHWTempMin"] = round(channel_info["setupDHWTempMin"]/ 2.0, 1)
            channel_info["setupDHWTempMax"] = round(channel_info["setupDHWTempMax"]/ 2.0, 1)

        return channel_info
        
    def is_available(self):
        return self.hub.connected

class MgppChannel:

    def __init__(self, channel_number, channel_info, hub, device_info, did_features=None) -> None:
        self.channel_number = channel_number
        self.channel_info = self.convert_channel_info(channel_info)
        self.hub = hub
        self.device_info = device_info
        self.mac_address = device_info.get("deviceInfo",{}).get("macAddress","") if device_info else ""
        self.callbacks = []
        self.channel_status = {}
        self.raw_responses = {
            'did': None,
            'status': None,
            'rsv': None
        }
        self.did_features = did_features or {}
        self.waiting_for_response = False

    def register_callback(self,callback):
        self.callbacks.append(callback)

    def deregister_callback(self,callback):
        if self.callbacks:
            self.callbacks.pop(self.callbacks.index(callback))

    def update_channel_status(self, response_type, response_data):
        """Update channel status with raw response data (no conversion here)."""
        self.raw_responses[response_type] = response_data
        _LOGGER.debug(f"MGPP {response_type.upper()} Response: {json.dumps(response_data, indent=2)}")

        # Store raw status dictionary as-is; conversions will be handled by entities
        if response_type == 'status' and 'response' in response_data:
            status_data = response_data['response'].get('status', {})
            self.channel_status = status_data
        elif response_type == 'status':
            # Fallback for unexpected structure: keep full payload
            self.channel_status = response_data

        if not self.waiting_for_response:
            self.publish_update()

    def publish_update(self):
        if len(self.callbacks) > 0:
            # Schedule callbacks on the main event loop to avoid threading issues
            for callback in self.callbacks:
                self.hub.loop.call_soon_threadsafe(callback)

    async def set_power_state(self, state):
        """Set MGPP device power state"""
        if not self.waiting_for_response:
            self.waiting_for_response = True
            await self.hub._mgpp_power_command(self.mac_address, state, self.channel_number)
            self.publish_update()
            self.waiting_for_response = False


    def _celsius_to_raw(self, celsius):
        """Convert Celsius to raw protocol value (half-degree encoding)"""
        return int(round(celsius * 2))

    async def set_temperature(self, temp_celsius):
        """Set MGPP device temperature"""
        if not self.waiting_for_response:
            self.waiting_for_response = True
            raw_temp = self._celsius_to_raw(temp_celsius)
            await self.hub._mgpp_temperature_command(self.mac_address, raw_temp, self.channel_number)
            self.publish_update()
            self.waiting_for_response = False

    async def set_operation_mode(self, mode):
        """Set MGPP operation mode"""
        if not self.waiting_for_response:
            self.waiting_for_response = True
            await self.hub._mgpp_operation_mode_command(self.mac_address, mode, self.channel_number)
            self.publish_update()
            self.waiting_for_response = False

    async def set_anti_legionella_state(self, state):
        """Set MGPP anti-legionella state"""
        if not self.waiting_for_response:
            self.waiting_for_response = True
            await self.hub._mgpp_anti_legionella_command(self.mac_address, state, self.channel_number)
            self.publish_update()
            self.waiting_for_response = False

    async def set_freeze_protection_state(self, state):
        """Set MGPP freeze protection state"""
        if not self.waiting_for_response:
            self.waiting_for_response = True
            await self.hub._mgpp_freeze_protection_command(self.mac_address, state, self.channel_number)
            self.publish_update()
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
        
        # Power status
        if self.channel_status.get('powerStatus', False):
            status_parts.append("ON")
        else:
            status_parts.append("OFF")
        
        # Temperature
        temp = self.channel_status.get('dhwTemperature', 0)
        target_temp = self.channel_status.get('dhwTemperatureSetting', 0)
        status_parts.append(f"Temp: {temp}°F (Target: {target_temp}°F)")
        
        # Error status
        if self.channel_status.get('hasError', False):
            error_msg = self.get_error_message()
            status_parts.append(f"ERROR: {error_msg}")
        
        # Operation mode
        if self.channel_status.get('isHeating', False):
            status_parts.append("HEATING")
        
        # Eco mode
        if self.channel_status.get('isEcoMode', False):
            status_parts.append("ECO MODE")
        
        return " | ".join(status_parts)

    def convert_channel_info(self, channel_info):
        """Convert channel info to include required fields for water_heater.py compatibility"""
        # Add default temperature type if not present (default to Fahrenheit for MGPP devices)
        if "temperatureType" not in channel_info:
            channel_info["temperatureType"] = TemperatureType.FAHRENHEIT.value
        
        # Add default temperature ranges if not present
        if "setupDHWTempMin" not in channel_info:
            channel_info["setupDHWTempMin"] = 100  # 100°F default minimum
        if "setupDHWTempMax" not in channel_info:
            channel_info["setupDHWTempMax"] = 140  # 140°F default maximum
        
        # Convert temperature ranges if using Celsius
        if channel_info.get("temperatureType", TemperatureType.FAHRENHEIT.value) == TemperatureType.CELSIUS.value:
            channel_info["setupDHWTempMin"] = round(channel_info["setupDHWTempMin"] / 2.0, 1)
            channel_info["setupDHWTempMax"] = round(channel_info["setupDHWTempMax"] / 2.0, 1)
        
        return channel_info

    def is_available(self):
        return self.hub.connected

class MgppTopics:
    def __init__(self, user_info, device_info, client_id) -> None:
        self.user_seq = str(user_info.get("userInfo",{}).get("userSeq",""))
        self.mac_address = device_info.get("deviceInfo",{}).get("macAddress","")
        self.home_seq = str(device_info.get("deviceInfo",{}).get("homeSeq",""))
        self.device_type = str(device_info.get("deviceInfo",{}).get("deviceType",""))
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

    # other mgpp endpoints:
    # st/energy-usage-daily-query/rd
    # st/energy-usage-monthly-query/rd

class Topics:

    def __init__(self, user_info, device_info, client_id) -> None:
        self.user_seq = str(user_info.get("userInfo",{}).get("userSeq",""))
        self.mac_address = device_info.get("deviceInfo",{}).get("macAddress","")
        self.home_seq = str(device_info.get("deviceInfo",{}).get("homeSeq",""))
        self.device_type = str(device_info.get("deviceInfo",{}).get("deviceType",""))
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

    # other mgpp endpoints:
    # st/energy-usage-daily-query/rd
    # st/energy-usage-monthly-query/rd

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
        self.mac_address = device_info.get("deviceInfo",{}).get("macAddress","")
        self.device_type = int(device_info.get("deviceInfo",{}).get("deviceType",1))
        self.additional_value = device_info.get("deviceInfo",{}).get("additionalValue","")   
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
        # POWER_OFF = 33554433, POWER_ON = 33554434 per spec
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
        # DHW_TEMPERATURE = 33554464 per spec
        # temp is already encoded (half-degree Celsius: celsius * 2)
        return {
            "clientID": self.client_id,
            "protocolVersion": 2,
            "request": {
                "additionalValue": self.additional_value,
                "command": 33554464,  # DHW_TEMPERATURE per spec
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

    def mgpp_operation_mode(self, mode, channel_number):
        """MGPP operation mode control message - uses RequestMgppControl structure per spec"""
        # DHW_OPERATION_MODE = 33554437 per spec
        # If mode is VACATION (5), include days parameter
        param = [mode]
        if mode == 5:  # VACATION mode requires days parameter
            # Default to 7 days if not specified
            param = [mode, 7]
        return {
            "clientID": self.client_id,
            "protocolVersion": 2,
            "request": {
                "additionalValue": self.additional_value,
                "command": 33554437,  # DHW_OPERATION_MODE per spec
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
        # ANTI_LEGIONELLA_OFF = 33554471, ANTI_LEGIONELLA_ON = 33554472 per spec
        command_id = 33554472 if state else 33554471
        mode_str = "anti-leg-on" if state else "anti-leg-off"
        # If enabling, include period parameter (default 7 days)
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
        # Note: FREZ_TEMP = 33554451 per spec, but no handler defined in app
        # This may need to be implemented differently - using a generic control structure
        # For now, using a placeholder command ID as freeze protection control isn't fully documented
        # The spec shows FREZ_TEMP exists but has no handler
        state_value = 2 if state else 1  # MGPP uses 1=off, 2=on
        return {
            "clientID": self.client_id,
            "protocolVersion": 2,
            "request": {
                "additionalValue": self.additional_value,
                "command": 33554451,  # FREZ_TEMP per spec (though no handler in app)
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
            "protocolVersion": 1,  # Last Will uses protocolVersion 1 per spec
            "requestTopic": self.topics.app_connection(),
            "sessionID": ""
        }

class Messages:

    def __init__(self, device_info, client_id, topics) -> None:
        self.mac_address = device_info.get("deviceInfo",{}).get("macAddress","")
        self.device_type = int(device_info.get("deviceInfo",{}).get("deviceType",1))
        self.additional_value = device_info.get("deviceInfo",{}).get("additionalValue","")   
        self.client_id = client_id
        self.topics = topics

    def channel_info(self):
        return {
            "clientID": self.client_id,
            "protocolVersion":1,
            "request":{"additionalValue":self.additional_value,"command":16777217,"deviceType":self.device_type,"macAddress":self.mac_address},
            "requestTopic":self.topics.start(),
            "responseTopic":self.topics.channel_info_res(),
            "sessionID":""
        }

    def channel_status(self,channel_number,unit_count):
        return {
            "clientID": self.client_id,
            "protocolVersion":1,
            "request":{"additionalValue":self.additional_value,"command":16777220,"deviceType":self.device_type,"macAddress":self.mac_address,"status":{"channelNumber":channel_number,"unitNumberEnd":unit_count,"unitNumberStart":1}},
            "requestTopic": self.topics.channel_status_req(),
            "responseTopic": self.topics.channel_status_res(),
            "sessionID": ""
        }

    def power(self, state, channel_number):
        return {
            "clientID": self.client_id,
            "protocolVersion":1,
            "request":{"additionalValue":self.additional_value,"command":33554433,"control":{"channelNumber":channel_number,"mode":"power","param":[state]},"deviceType":self.device_type,"macAddress":self.mac_address},
            "requestTopic": self.topics.control(),
            "responseTopic": self.topics.channel_status_res(),
            "sessionID": ""
        }

    def hot_button(self, state, channel_number):
        return {
            "clientID": self.client_id,
            "protocolVersion":1,
            "request":{"additionalValue":self.additional_value,"command":33554437,"control":{"channelNumber":channel_number,"mode":"onDemand","param":[state]},"deviceType":self.device_type,"macAddress":self.mac_address},
            "requestTopic": self.topics.control(),
            "responseTopic": self.topics.channel_status_res(),
            "sessionID": ""
        }

    def temperature(self, temp, channel_number):
        return {
            "clientID": self.client_id,
            "protocolVersion":1,
            "request":{"additionalValue":self.additional_value,"command":33554435,"control":{"channelNumber":channel_number,"mode":"DHWTemperature","param":[temp]},"deviceType":self.device_type,"macAddress":self.mac_address},
            "requestTopic": self.topics.control(),
            "responseTopic": self.topics.channel_status_res(),
            "sessionID": ""
        }

    def last_will(self):
        return {
            "clientID": self.client_id,
            "event":{"additionalValue":self.additional_value,"connection":{"os":"A","status":0},"deviceType":self.device_type,"macAddress":self.mac_address},
            "protocolVersion":1,
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

class NoChannelInformation(Exception):
    """No Channel Information"""

class NoAccessKey(Exception):
    """Access key, Secret key, or Session token missing"""
