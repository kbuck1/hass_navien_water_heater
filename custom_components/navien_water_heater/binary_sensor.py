"""Support for Navien NaviLink binary sensors."""
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import NavienBaseEntity
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

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return f"{self._device.device_identifier}_{self.sensor_key}"

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
