"""Support for Navien NaviLink binary sensors."""
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .navien_api import MgppChannel
from .const import DOMAIN
import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Navien binary sensors based on a config entry."""
    navilink = hass.data[DOMAIN][entry.entry_id]
    sensors = []
    for device_key, channel in navilink.devices.items():
        mac_address, channel_number = device_key
        if isinstance(channel, MgppChannel):
            # One set of MGPP diagnostic sensors - disabled by default
            sensors.extend([
                MgppBinarySensor(navilink, channel, 'heatUpperUse', 'Upper Heating Element',
                                device_class=BinarySensorDeviceClass.HEAT, enabled_default=False),
                MgppBinarySensor(navilink, channel, 'heatLowerUse', 'Lower Heating Element',
                                device_class=BinarySensorDeviceClass.HEAT, enabled_default=False),
                MgppBinarySensor(navilink, channel, 'compUse', 'Heat Pump Compressor',
                                device_class=BinarySensorDeviceClass.RUNNING, enabled_default=False),
                MgppBinarySensor(navilink, channel, 'evaFanUse', 'Evaporator Fan',
                                device_class=BinarySensorDeviceClass.RUNNING, enabled_default=False),
                MgppBinarySensor(navilink, channel, 'eevUse', 'Electronic Expansion Valve',
                                device_class=BinarySensorDeviceClass.RUNNING, enabled_default=False),
                MgppBinarySensor(navilink, channel, 'operationBusy', 'System Heating',
                                device_class=BinarySensorDeviceClass.RUNNING, enabled_default=False),
            ])
    async_add_entities(sensors)


class MgppBinarySensor(BinarySensorEntity):
    """Representation of an MGPP diagnostic binary sensor"""

    def __init__(self, navilink, channel, sensor_key, name, device_class=None, enabled_default=True):
        self.navilink = navilink
        self.channel = channel
        self.sensor_key = sensor_key
        self._name = name
        self._device_class = device_class
        self._enabled_default = enabled_default

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self.channel.register_callback(self.update_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self.channel.deregister_callback(self.update_state)

    def update_state(self):
        self.async_write_ha_state()

    @property
    def available(self):
        """Return if the the sensor is online or not."""
        return self.channel.is_available()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        mac = self.channel.device_info.get("deviceInfo",{}).get("macAddress","unknown")
        name = self.channel.device_info.get("deviceInfo",{}).get("deviceName","unknown")
        return DeviceInfo(
            identifiers = {(DOMAIN, mac + "_" + str(self.channel.channel_number))},
            manufacturer = "Navien",
            name = name,
        )

    @property
    def name(self):
        """Return the name of the entity."""
        return self.channel.device_info.get("deviceInfo",{}).get("deviceName","UNKNOWN") + " " + self._name

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        mac = self.channel.device_info.get("deviceInfo",{}).get("macAddress","unknown")
        return mac + "_" + str(self.channel.channel_number) + "_" + self.sensor_key

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        """Return the class of this entity."""
        return self._device_class

    @property
    def is_on(self):
        """Return the state of the sensor."""
        # MGPP typically uses 1=off, 2=on for status flags
        return self.channel.channel_status.get(self.sensor_key, 0) == 2

    @property
    def entity_registry_enabled_default(self):
        """Return if the entity should be enabled by default."""
        return self._enabled_default
