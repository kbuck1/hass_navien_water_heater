"""Base entity for Navien Water Heater integration."""
from homeassistant.helpers.entity import DeviceInfo, Entity
from .const import DOMAIN


class NavienBaseEntity(Entity):
    """Base class for Navien entities.
    
    Entities bind to the coordinator and look up devices by device_identifier.
    This allows entities to survive device recreation during account-level reconnection.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator, device_identifier) -> None:
        """Initialize the base entity.
        
        Args:
            coordinator: NavilinkAccountCoordinator instance
            device_identifier: Unique identifier for the device
        """
        self._coordinator = coordinator
        self._device_identifier = device_identifier
        device = coordinator.get_device(device_identifier)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},
            manufacturer="Navien",
            name=device.device_name if device else "Unknown",
        )

    @property
    def device(self):
        """Return the current device from coordinator.
        
        This is a dynamic lookup so entities always get the current device,
        even after reconnection creates new device objects.
        """
        return self._coordinator.get_device(self._device_identifier)

    @property
    def available(self) -> bool:
        """Return if the device is online or not."""
        device = self.device
        return device is not None and device.is_available()

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self._coordinator.register_update_callback(
            self._device_identifier,
            self._handle_coordinator_update
        )

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self._coordinator.deregister_update_callback(
            self._device_identifier,
            self._handle_coordinator_update
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
