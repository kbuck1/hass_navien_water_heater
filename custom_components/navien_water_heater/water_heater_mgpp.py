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
from .navien_api import MgppDevice
from .mgpp_utils import to_celsius_display

_LOGGER = logging.getLogger(__name__)


class NavienWaterHeaterMgppEntity(NavienBaseEntity, WaterHeaterEntity):
    """MGPP Navien water heater entity."""

    def __init__(self, device: MgppDevice):
        """Initialize the MGPP water heater entity."""
        super().__init__(device)

    @property
    def name(self):
        """Return the name of the entity."""
        return self._device.device_name

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return f"{self._device.device_identifier}_water_heater"

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
        raw = self._device.channel_status.get("dhwTemperature", 0)
        return to_celsius_display(raw)

    @property
    def target_temperature(self):
        raw = self._device.channel_status.get("dhwTemperatureSetting", 0)
        return to_celsius_display(raw)

    @property
    def target_temperature_step(self):
        return 0.5

    @property
    def min_temp(self):
        return to_celsius_display(self._device.did_features.get("dhwTemperatureMin", 0))

    @property
    def max_temp(self):
        return to_celsius_display(self._device.did_features.get("dhwTemperatureMax", 0))

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
