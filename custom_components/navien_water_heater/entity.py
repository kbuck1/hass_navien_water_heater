"""Base entity for Navien Water Heater integration."""
from homeassistant.helpers.entity import DeviceInfo, Entity
from .const import DOMAIN


class NavienBaseEntity(Entity):
    """Base class for Navien entities."""

    def __init__(self, device) -> None:
        """Initialize the base entity.
        
        Args:
            device: NavilinkDevice or MgppDevice instance
        """
        self._device = device

    @property
    def device(self):
        """Return the device."""
        return self._device

    @property
    def available(self) -> bool:
        """Return if the device is online or not."""
        return self._device.is_available()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.device_identifier)},
            manufacturer="Navien",
            name=self._device.device_name,
        )

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self._device.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self._device.deregister_callback(self._handle_coordinator_update)

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

