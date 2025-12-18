"""Support for Navien NaviLink water heaters."""
import logging

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
    STATE_GAS,
    STATE_OFF,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import NavienBaseEntity
from .migration import get_legacy_unique_id_if_exists
from .navien_api import MgppDevice
from .water_heater_mgpp import NavienWaterHeaterMgppEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = (
    WaterHeaterEntityFeature.AWAY_MODE 
    | WaterHeaterEntityFeature.TARGET_TEMPERATURE 
    | WaterHeaterEntityFeature.OPERATION_MODE
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Navien water heater based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = []
    for device in coordinator.devices.values():
        if isinstance(device, MgppDevice):
            entities.append(NavienWaterHeaterMgppEntity(coordinator, device.device_identifier))
        else:
            entities.append(NavienWaterHeaterEntity(coordinator, device.device_identifier))
    
    async_add_entities(entities)


class NavienWaterHeaterEntity(NavienBaseEntity, WaterHeaterEntity):
    """Define a Navien water heater."""

    def __init__(self, coordinator, device_identifier):
        """Initialize the water heater entity."""
        super().__init__(coordinator, device_identifier)
        self._cached_unique_id = None

    _attr_name = None  # Use device name as entity name

    def _get_legacy_unique_id(self) -> str:
        """Return legacy unique_id format: {mac}{channel}"""
        return f"{self.device.mac_address}{self.device.channel_number}"

    def _get_new_unique_id(self) -> str:
        """Return new unique_id format: {mac}_{channel}_water_heater"""
        return f"{self._device_identifier}_water_heater"

    @property
    def unique_id(self):
        """Return the unique ID of the entity, using legacy format if it exists."""
        if self._cached_unique_id is not None:
            return self._cached_unique_id
        
        if self.hass is None:
            return self._get_new_unique_id()
        
        self._cached_unique_id = get_legacy_unique_id_if_exists(
            self.hass, "water_heater",
            self._get_legacy_unique_id(),
            self._get_new_unique_id(),
        )
        return self._cached_unique_id

    @property
    def temperature_unit(self):
        """Return the device's native temperature unit.
        
        Legacy devices can be configured for Celsius or Fahrenheit.
        Values from the API are already in the native unit.
        HA handles conversion to user's display preference.
        """
        return UnitOfTemperature.CELSIUS if self.device.is_celsius else UnitOfTemperature.FAHRENHEIT

    @property
    def is_away_mode_on(self):
        """Return true if away mode is on."""
        return not self.device.channel_status.get("powerStatus", False)

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_FLAGS

    @property
    def current_operation(self):
        """Return current operation."""
        return STATE_GAS if self.device.channel_status.get("powerStatus", False) else STATE_OFF

    @property
    def operation_list(self):
        """List of available operation modes."""
        return [STATE_OFF, STATE_GAS]

    @property
    def current_temperature(self):
        """Return the current hot water temperature."""
        unit_list = self.device.channel_status.get("unitInfo", {}).get("unitStatusList", [])
        if len(unit_list) > 0:
            return round(sum([unit_info.get("currentOutletTemp") for unit_info in unit_list]) / len(unit_list))
        else:
            _LOGGER.warning("No channel status information available for " + self.name)

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self.device.channel_status.get("DHWSettingTemp", 0)

    @property
    def target_temperature_step(self):
        """Returns the step size setting for temperature.
        
        Celsius devices use half-degree increments (0.5).
        Fahrenheit devices use whole degree increments (1).
        """
        return 0.5 if self.device.is_celsius else 1

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return self.device.channel_info.get("setupDHWTempMin", 0)

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return self.device.channel_info.get("setupDHWTempMax", 0)

    async def async_set_temperature(self, **kwargs):
        """Set target water temperature.
        
        Temperature is passed in the device's native unit (Celsius or Fahrenheit).
        The API layer handles wire protocol encoding.
        """
        target_temp = kwargs.get(ATTR_TEMPERATURE)
        await self.device.set_temperature(target_temp)

    async def async_turn_away_mode_on(self):
        """Turn away mode on."""
        await self.device.set_power_state(False)

    async def async_turn_away_mode_off(self):
        """Turn away mode off."""
        await self.device.set_power_state(True)

    async def async_set_operation_mode(self, operation_mode):
        """Set operation mode"""
        power_state = operation_mode == STATE_GAS
        await self.device.set_power_state(power_state)

    async def async_turn_on(self):
        """Turn the water heater on."""
        await self.device.set_power_state(True)

    async def async_turn_off(self):
        """Turn the water heater off."""
        await self.device.set_power_state(False)
