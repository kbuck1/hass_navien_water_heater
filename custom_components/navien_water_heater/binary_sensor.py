"""Support for Navien NaviLink binary sensors."""
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import NavienBaseEntity
from .migration import get_legacy_unique_id_if_exists
from .navien_api import MgppDevice
from .const import DOMAIN
import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Navien binary sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = []
    
    for device in coordinator.devices.values():
        if isinstance(device, MgppDevice):
            # MGPP diagnostic sensors - disabled by default
            sensors.extend([
                MgppBinarySensor(device, 'heatUpperUse', 'Upper Heating Element',
                                device_class=BinarySensorDeviceClass.HEAT, enabled_default=False),
                MgppBinarySensor(device, 'heatLowerUse', 'Lower Heating Element',
                                device_class=BinarySensorDeviceClass.HEAT, enabled_default=False),
                MgppBinarySensor(device, 'compUse', 'Heat Pump Compressor',
                                device_class=BinarySensorDeviceClass.RUNNING, enabled_default=False),
                MgppBinarySensor(device, 'evaFanUse', 'Evaporator Fan',
                                device_class=BinarySensorDeviceClass.RUNNING, enabled_default=False),
                MgppBinarySensor(device, 'eevUse', 'Electronic Expansion Valve',
                                device_class=BinarySensorDeviceClass.RUNNING, enabled_default=False),
                MgppBinarySensor(device, 'operationBusy', 'System Heating',
                                device_class=BinarySensorDeviceClass.RUNNING, enabled_default=False),
            ])
    
    async_add_entities(sensors)


class MgppBinarySensor(NavienBaseEntity, BinarySensorEntity):
    """Representation of an MGPP diagnostic binary sensor"""

    def __init__(self, device, sensor_key, name, device_class=None, enabled_default=True):
        super().__init__(device)
        self.sensor_key = sensor_key
        self._attr_name = name
        self._device_class = device_class
        self._enabled_default = enabled_default
        self._cached_unique_id = None

    def _get_legacy_unique_id(self) -> str:
        """Return legacy unique_id format: {mac}{key}"""
        return f"{self._device.mac_address}{self.sensor_key}"

    def _get_new_unique_id(self) -> str:
        """Return new unique_id format: {mac}_{key}"""
        return f"{self._device.device_identifier}_{self.sensor_key}"

    @property
    def unique_id(self):
        """Return the unique ID of the entity, using legacy format if it exists."""
        if self._cached_unique_id is not None:
            return self._cached_unique_id
        
        if self.hass is None:
            return self._get_new_unique_id()
        
        self._cached_unique_id = get_legacy_unique_id_if_exists(
            self.hass, "binary_sensor",
            self._get_legacy_unique_id(),
            self._get_new_unique_id(),
        )
        return self._cached_unique_id

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        """Return the class of this entity."""
        return self._device_class

    @property
    def is_on(self):
        """Return the state of the sensor."""
        # MGPP typically uses 1=off, 2=on for status flags
        return self._device.channel_status.get(self.sensor_key, 0) == 2

    @property
    def entity_registry_enabled_default(self):
        """Return if the entity should be enabled by default."""
        return self._enabled_default
