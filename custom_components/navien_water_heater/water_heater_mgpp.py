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
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .entity import NavienBaseEntity
from .migration import get_legacy_unique_id_if_exists
from .navien_api import MgppDevice

_LOGGER = logging.getLogger(__name__)


class NavienWaterHeaterMgppEntity(NavienBaseEntity, WaterHeaterEntity):
    """MGPP Navien water heater entity."""

    def __init__(self, device: MgppDevice):
        """Initialize the MGPP water heater entity."""
        super().__init__(device)
        self._cached_unique_id = None

    _attr_name = None  # Use device name as entity name

    def _get_legacy_unique_id(self) -> str:
        """Return legacy unique_id format: {mac}_wh"""
        return f"{self._device.mac_address}_wh"

    def _get_new_unique_id(self) -> str:
        """Return new unique_id format: {mac}_water_heater"""
        return f"{self._device.device_identifier}_water_heater"

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
        return self._device.channel_status.get("dhwOperationSetting", 0) == 5

    @property
    def current_operation(self):
        mode = self._device.channel_status.get("dhwOperationSetting", 6)
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
        """Current DHW temperature in Celsius."""
        return self._device.dhw_temperature

    @property
    def target_temperature(self):
        """Target DHW temperature in Celsius."""
        return self._device.dhw_temperature_setting

    @property
    def target_temperature_step(self):
        """MGPP uses half-degree Celsius increments."""
        return 0.5

    @property
    def min_temp(self):
        """Minimum temperature in Celsius."""
        return self._device.dhw_temperature_min

    @property
    def max_temp(self):
        """Maximum temperature in Celsius."""
        return self._device.dhw_temperature_max

    async def async_set_temperature(self, **kwargs):
        target_c = kwargs.get(ATTR_TEMPERATURE)
        await self._device.set_temperature(target_c)

    async def async_turn_away_mode_on(self):
        # Vacation - use the vacation_days value from the device
        await self._device.set_operation_mode(5)

    async def async_turn_away_mode_off(self):
        # Default back to heat pump
        await self._device.set_operation_mode(1)

    async def async_set_operation_mode(self, operation_mode):
        # STATE_OFF should use power command, not operation mode
        if operation_mode == STATE_OFF:
            await self._device.set_power_state(False)
            return

        mode_map = {
            STATE_HEAT_PUMP: 1,
            STATE_ELECTRIC: 2,
            STATE_ECO: 3,
            STATE_HIGH_DEMAND: 4,
        }
        await self._device.set_operation_mode(mode_map.get(operation_mode, 1))

    async def async_turn_on(self):
        await self._device.set_power_state(True)

    async def async_turn_off(self):
        await self._device.set_power_state(False)
