"""MGPP-specific water heater implementation for Navien NaviLink."""
import logging

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
    STATE_ECO,
    STATE_ELECTRIC,
    STATE_HEAT_PUMP,
    STATE_HIGH_DEMAND,
    STATE_OFF,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .navien_api import MgppChannel
from .const import DOMAIN
from .mgpp_utils import to_celsius_display

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry_mgpp(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up MGPP Navien water heater based on a config entry."""
    navilink = hass.data[DOMAIN][entry.entry_id]

    # Find MGPP channels
    mgpp_channels = []
    for device_key, channel in navilink.devices.items():
        mac_address, channel_number = device_key
        if isinstance(channel, MgppChannel) and navilink.is_mgpp_device(mac_address):
            mgpp_channels.append(channel)

    if not mgpp_channels:
        _LOGGER.warning("No MGPP channel found during MGPP water heater setup")
        return

    async_add_entities([NavienWaterHeaterMgppEntity(hass, channel, navilink) for channel in mgpp_channels])


class NavienWaterHeaterMgppEntity(WaterHeaterEntity):
    """MGPP Navien water heater entity."""

    def __init__(self, hass, channel: MgppChannel, navilink):
        self.hass = hass
        self.channel = channel
        self.navilink = navilink

    async def async_added_to_hass(self) -> None:
        self.channel.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        self.channel.deregister_callback(self.async_write_ha_state)

    @property
    def available(self):
        return self.channel.is_available()

    @property
    def device_info(self) -> DeviceInfo:
        mac = self.channel.device_info.get("deviceInfo", {}).get("macAddress", "unknown")
        name = self.channel.device_info.get("deviceInfo", {}).get("deviceName", "unknown")
        return DeviceInfo(
            identifiers={(DOMAIN, mac + "_" + str(self.channel.channel_number))},
            manufacturer="Navien",
            name=name,
        )

    @property
    def name(self):
        return self.channel.device_info.get("deviceInfo", {}).get("deviceName", "UNKNOWN")

    @property
    def unique_id(self):
        mac = self.channel.device_info.get("deviceInfo", {}).get("macAddress", "unknown")
        return f"{mac}_wh_{self.channel.channel_number}"

    @property
    def temperature_unit(self):
        return UnitOfTemperature.CELSIUS

    @property
    def supported_features(self):
        return (
            WaterHeaterEntityFeature.TARGET_TEMPERATURE
            | WaterHeaterEntityFeature.OPERATION_MODE
            | WaterHeaterEntityFeature.AWAY_MODE
            | WaterHeaterEntityFeature.ON_OFF
        )

    @property
    def is_away_mode_on(self):
        # MGPP vacation = 5
        return self.channel.channel_status.get("dhwOperationSetting", 0) == 5

    @property
    def current_operation(self):
        mode = self.channel.channel_status.get("dhwOperationSetting", 6)
        mode_map = {
            0: STATE_OFF,  # standby
            1: STATE_HEAT_PUMP,
            2: STATE_ELECTRIC,
            3: STATE_ECO,
            4: STATE_HIGH_DEMAND,
            5: STATE_OFF,  # vacation
            6: STATE_OFF,  # power off
        }
        return mode_map.get(mode, STATE_OFF)

    @property
    def operation_list(self):
        return [STATE_HEAT_PUMP, STATE_ELECTRIC, STATE_ECO, STATE_HIGH_DEMAND, STATE_OFF]

    @property
    def current_temperature(self):
        # Raw value is half-degree C for display temps
        raw = self.channel.channel_status.get("dhwTemperature", 0)
        return to_celsius_display(raw)

    @property
    def target_temperature(self):
        raw = self.channel.channel_status.get("dhwTemperatureSetting", 0)
        return to_celsius_display(raw)

    @property
    def target_temperature_step(self):
        return 0.5

    @property
    def min_temp(self):
        return to_celsius_display(self.channel.did_features.get("dhwTemperatureMin", 0))

    @property
    def max_temp(self):
        return to_celsius_display(self.channel.did_features.get("dhwTemperatureMax", 0))

    async def async_set_temperature(self, **kwargs):
        target_c = kwargs.get(ATTR_TEMPERATURE)
        await self.channel.set_temperature(target_c)

    async def async_turn_away_mode_on(self):
        # Vacation
        await self.channel.set_operation_mode(5)

    async def async_turn_away_mode_off(self):
        # Default back to heat pump
        await self.channel.set_operation_mode(1)

    async def async_set_operation_mode(self, operation_mode):
        mode_map = {
            STATE_HEAT_PUMP: 1,
            STATE_ELECTRIC: 2,
            STATE_ECO: 3,
            STATE_HIGH_DEMAND: 4,
            STATE_OFF: 6,
        }
        await self.channel.set_operation_mode(mode_map.get(operation_mode, 6))

    async def async_turn_on(self):
        await self.channel.set_operation_mode(1)

    async def async_turn_off(self):
        await self.channel.set_operation_mode(6)


