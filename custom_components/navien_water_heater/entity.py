"""Base entity for Navien Water Heater integration."""
from homeassistant.helpers.entity import DeviceInfo, Entity
from .const import DOMAIN


class NavienBaseEntity(Entity):
    """Base class for Navien entities."""

    _attr_has_entity_name = True

    def __init__(self, device) -> None:
        """Initialize the base entity.
        
        Args:
            device: NavilinkDevice or MgppDevice instance
        """
        self._device = device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_identifier)},
            manufacturer="Navien",
            name=device.device_name,
        )

    @property
    def device(self):
        """Return the device."""
        return self._device

    @property
    def available(self) -> bool:
        """Return if the device is online or not."""
        return self._device.is_available()


    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self._device.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self._device.deregister_callback(self._handle_coordinator_update)

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

