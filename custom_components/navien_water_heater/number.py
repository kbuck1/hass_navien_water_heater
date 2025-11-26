"""Support for Navien NaviLink water heater vacation mode duration."""
import logging

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import NavienBaseEntity
from .navien_api import MgppDevice
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Navien vacation mode duration number entity based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    devices = []
    
    for device in coordinator.devices.values():
        if isinstance(device, MgppDevice):
            # Only create for MGPP devices
            devices.append(NavienVacationModeDurationNumberEntity(device))
    
    async_add_entities(devices)


class NavienVacationModeDurationNumberEntity(NavienBaseEntity, NumberEntity):
    """Representation of a Navien vacation mode duration number entity."""

    def __init__(self, device: MgppDevice):
        """Initialize the vacation mode duration number entity."""
        super().__init__(device)
        self._value = 7  # Default to 7 days

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        await super().async_added_to_hass()
        # Try to restore the value from channel status if available
        vacation_days = self._device.channel_status.get("vacationDaySetting")
        if vacation_days is not None and vacation_days > 0:
            self._value = int(vacation_days)
            self._device.vacation_days = int(vacation_days)
        else:
            # Ensure default is 7 if no valid value from device
            self._value = 7
            # Initialize device's vacation_days with our default value
            self._device.vacation_days = self._value

    @property
    def name(self):
        """Return the name of the entity."""
        return f"{self._device.device_name} Vacation Mode Duration"

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return f"{self._device.device_identifier}_vacation_mode_duration"

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return float(self._value)

    @property
    def native_min_value(self) -> float:
        """Return the minimum value."""
        return 1.0

    @property
    def native_max_value(self) -> float:
        """Return the maximum value."""
        return 99.0

    @property
    def native_step(self) -> float:
        """Return the step value."""
        return 1.0

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return "days"

    @property
    def mode(self) -> str:
        """Return the display mode."""
        return "box"

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        # Ensure value is a whole number between 1 and 99
        days = int(max(1, min(99, round(value))))
        self._value = days
        # Update the device's vacation_days so it's used when vacation mode is enabled
        self._device.vacation_days = days
        _LOGGER.debug(f"Vacation mode duration set to {days} days")
        self.async_write_ha_state()
