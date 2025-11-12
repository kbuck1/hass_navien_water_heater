"""Support for Navien NaviLink water heater vacation mode duration."""
import logging

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from .navien_api import MgppChannel
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Navien vacation mode duration number entity based on a config entry."""
    navilink = hass.data[DOMAIN][entry.entry_id]
    devices = []
    for channel in navilink.channels.values():
        if isinstance(channel, MgppChannel):
            # Only create for MGPP devices
            devices.append(NavienVacationModeDurationNumberEntity(navilink, channel))
    async_add_entities(devices)


class NavienVacationModeDurationNumberEntity(NumberEntity):
    """Representation of a Navien vacation mode duration number entity."""

    def __init__(self, navilink, channel: MgppChannel):
        """Initialize the vacation mode duration number entity."""
        self.navilink = navilink
        self.channel = channel
        self._value = 7  # Default to 7 days

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Try to restore the value from channel status if available
        vacation_days = self.channel.channel_status.get("vacationDaySetting")
        if vacation_days is not None:
            self._value = int(vacation_days)
            self.channel.vacation_days = int(vacation_days)
        else:
            # Initialize channel's vacation_days with our default value
            self.channel.vacation_days = self._value

    @property
    def available(self):
        """Return if the device is online or not."""
        return self.channel.is_available()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        mac = self.navilink.device_info.get("deviceInfo", {}).get("macAddress", "unknown")
        name = self.navilink.device_info.get("deviceInfo", {}).get("deviceName", "unknown")
        return DeviceInfo(
            identifiers={(DOMAIN, mac)},
            manufacturer="Navien",
            name=name,
        )

    @property
    def name(self):
        """Return the name of the entity."""
        return self.navilink.device_info.get("deviceInfo", {}).get("deviceName", "UNKNOWN") + " Vacation Mode Duration"

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        mac = self.navilink.device_info.get("deviceInfo", {}).get("macAddress", "unknown")
        return f"{mac}_vacation_mode_duration"

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

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        # Ensure value is a whole number between 1 and 99
        days = int(max(1, min(99, round(value))))
        self._value = days
        # Update the channel's vacation_days so it's used when vacation mode is enabled
        self.channel.vacation_days = days
        _LOGGER.debug(f"Vacation mode duration set to {days} days")
        self.async_write_ha_state()