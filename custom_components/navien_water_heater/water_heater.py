"""Support for Navien NaviLink water heaters."""
import logging

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
    STATE_GAS,
    STATE_ECO,
    STATE_ELECTRIC,
    STATE_HEAT_PUMP,
    STATE_HIGH_DEMAND,
    STATE_OFF,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from .navien_api import TemperatureType, MgppChannel
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = (
    WaterHeaterEntityFeature.AWAY_MODE | WaterHeaterEntityFeature.TARGET_TEMPERATURE | WaterHeaterEntityFeature.OPERATION_MODE
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Navien water heater based on a config entry."""
    navilink = hass.data[DOMAIN][entry.entry_id]
    devices = []
    for channel in navilink.channels.values():
        devices.append(NavienWaterHeaterEntity(hass, channel,navilink))
    async_add_entities(devices)


class NavienWaterHeaterEntity(WaterHeaterEntity):
    """Define a Navien water heater."""

    def __init__(self, hass, channel, navilink):
        self.hass = hass
        self.channel = channel
        self.navilink = navilink
    
    def _is_mgpp_device(self):
        """Check if this is an MGPP protocol device"""
        return isinstance(self.channel, MgppChannel)

    @property
    def available(self):
        """Return if the the device is online or not."""
        return self.channel.is_available()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        return DeviceInfo(
            identifiers = {(DOMAIN, self.navilink.device_info.get("deviceInfo",{}).get("macAddress","unknown") + "_" + str(self.channel.channel_number))},
            manufacturer = "Navien",
            name = self.navilink.device_info.get("deviceInfo",{}).get("deviceName","unknown") + " CH" + str(self.channel.channel_number),
        )

    @property
    def name(self):
        """Return the name of the entity."""
        return self.navilink.device_info.get("deviceInfo",{}).get("deviceName","UNKNOWN") + " CH" + str(self.channel.channel_number)

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return self.navilink.device_info.get("deviceInfo",{}).get("macAddress","unknown") + str(self.channel.channel_number)

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self.channel.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self.channel.deregister_callback(self.async_write_ha_state)

    @property
    def temperature_unit(self):
        """Return temperature unit - always Celsius, HA converts to user preference"""
        return UnitOfTemperature.CELSIUS

    @property
    def is_away_mode_on(self):
        """Return true if away mode is on."""
        if self._is_mgpp_device():
            return self.channel.channel_status.get("dhwOperationSetting", 0) == 5  # VACATION
        return not self.channel.channel_status.get("powerStatus", False)

    @property
    def supported_features(self):
        """Return the list of supported features."""
        features = SUPPORT_FLAGS
        if self._is_mgpp_device():
            features |= WaterHeaterEntityFeature.ON_OFF
        return features

    @property
    def current_operation(self):
        """Return current operation."""
        if self._is_mgpp_device():
            mode = self.channel.channel_status.get("dhwOperationSetting", 6)
            # Map MGPP mode to HA state
            mode_map = {
                0: STATE_OFF,  # STANDBY
                1: STATE_HEAT_PUMP,
                2: STATE_ELECTRIC,
                3: STATE_ECO,
                4: STATE_HIGH_DEMAND,
                5: STATE_OFF,  # VACATION shown as off
                6: STATE_OFF,  # POWER_OFF
            }
            return mode_map.get(mode, STATE_OFF)
        else:
            return STATE_GAS if self.channel.channel_status.get("powerStatus", False) else STATE_OFF

    @property
    def operation_list(self):
        """List of available operation modes."""
        if self._is_mgpp_device():
            return [STATE_HEAT_PUMP, STATE_ELECTRIC, STATE_ECO, STATE_HIGH_DEMAND, STATE_OFF]
        return [STATE_OFF, STATE_GAS]
    
    @property
    def current_temperature(self):
        """Return the current hot water temperature."""
        if self._is_mgpp_device():
            # MGPP: temperatures are already converted to Celsius in navien_api.py
            return self.channel.channel_status.get("dhwTemperature", 0)
        else:
            # Legacy: get from unitInfo structure
            unit_list = self.channel.channel_status.get("unitInfo",{}).get("unitStatusList",[])
            if len(unit_list) > 0:
                return round(sum([unit_info.get("currentOutletTemp") for unit_info in unit_list])/len(unit_list))
            else:
                _LOGGER.warning("No channel status information available for " + self.name)

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        if self._is_mgpp_device():
            # MGPP: temperatures are already converted to Celsius in navien_api.py
            return self.channel.channel_status.get("dhwTemperatureSetting", 0)
        else:
            # Legacy: use DHWSettingTemp field
            return self.channel.channel_status.get("DHWSettingTemp", 0)

    @property
    def target_temperature_step(self):
        """Returns the step size setting for temperature."""
        return 0.5;

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self._is_mgpp_device():
            return self.channel.did_features.get("dhwTemperatureMin",0) / 2.0
        return self.channel.channel_info.get("setupDHWTempMin",0)

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self._is_mgpp_device():
            return self.channel.did_features.get("dhwTemperatureMax",0) / 2.0
        return self.channel.channel_info.get("setupDHWTempMax",0)

    async def async_set_temperature(self, **kwargs):
        """Set target water temperature"""
        target_temp = kwargs.get(ATTR_TEMPERATURE)
        if self._is_mgpp_device():
            # MGPP: navien_api handles conversion to raw
            await self.channel.set_temperature(target_temp)
        else:
            # Legacy: expects raw value (half-degree celsius)
            await self.channel.set_temperature(target_temp * 2)


    async def async_turn_away_mode_on(self):
        """Turn away mode on."""
        if self._is_mgpp_device():
            await self.channel.set_operation_mode(5)  # VACATION
        else:
            await self.channel.set_power_state(False)

    async def async_turn_away_mode_off(self):
        """Turn away mode off."""
        if self._is_mgpp_device():
            # Restore to heat pump mode (safest default)
            await self.channel.set_operation_mode(1)
        else:
            await self.channel.set_power_state(True)

    async def async_set_operation_mode(self, operation_mode):
        """Set operation mode"""
        if self._is_mgpp_device():
            # Map HA state to MGPP mode
            mode_map = {
                STATE_HEAT_PUMP: 1,
                STATE_ELECTRIC: 2,
                STATE_ECO: 3,
                STATE_HIGH_DEMAND: 4,
                STATE_OFF: 6,
            }
            mgpp_mode = mode_map.get(operation_mode, 6)
            await self.channel.set_operation_mode(mgpp_mode)
        else:
            # Legacy: only supports on/off
            power_state = operation_mode == STATE_GAS
            await self.channel.set_power_state(power_state)

    async def async_turn_on(self):
        """Turn the water heater on."""
        if self._is_mgpp_device():
            await self.channel.set_operation_mode(1)  # Heat pump mode
        else:
            await self.channel.set_power_state(True)

    async def async_turn_off(self):
        """Turn the water heater off."""
        if self._is_mgpp_device():
            await self.channel.set_operation_mode(6)  # Power off
        else:
            await self.channel.set_power_state(False)
