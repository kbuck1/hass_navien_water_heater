"""Support for Navien NaviLink water heaters On Demand/External Recirculator."""
from homeassistant.components.switch import (
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from .navien_api import DeviceSorting, MgppChannel
from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Navien On Demand switch based on a config entry."""
    navilink = hass.data[DOMAIN][entry.entry_id]
    devices = []
    for channel in navilink.channels.values():
        if isinstance(channel, MgppChannel):
            # One set of MGPP-specific switches
            devices.append(MgppAntiLegionellaSwitchEntity(navilink, channel))
            devices.append(MgppFreezeProtectionSwitchEntity(navilink, channel))
        else:
            # Legacy switches
            if channel.channel_info.get("onDemandUse",2) == 1:
                devices.append(NavienOnDemandSwitchEntity(navilink, channel))
            devices.append(NavienPowerSwitchEntity(navilink, channel))        
    async_add_entities(devices)


class NavienOnDemandSwitchEntity(SwitchEntity):
    """Define a Navien Hot Button/On Demand/External Recirculator Entity."""

    def __init__(self, navilink, channel):
        self.navilink = navilink
        self.channel = channel

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self.channel.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self.channel.deregister_callback(self.async_write_ha_state)

    @property
    def available(self):
        """Return if the the device is online or not."""
        return self.channel.is_available()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        mac = self.navilink.device_info.get("deviceInfo",{}).get("macAddress","unknown")
        name = self.navilink.device_info.get("deviceInfo",{}).get("deviceName","unknown")
        return DeviceInfo(
            identifiers = {(DOMAIN, mac)},
            manufacturer = "Navien",
            name = name
        )

    @property
    def name(self):
        """Return the name of the entity."""
        return self.navilink.device_info.get("deviceInfo",{}).get("deviceName","UNKNOWN") + " Hot Button CH" + str(self.channel.channel_number)

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return self.navilink.device_info.get("deviceInfo",{}).get("macAddress","unknown") + str(self.channel.channel_number) + "hot_button"

    @property
    def is_on(self):
        """Return the current On Demand state."""
        return self.channel.channel_status.get("onDemandUseFlag",False)

    async def async_turn_on(self):
        """Turn On Hot Button."""
        await self.channel.set_hot_button_state(True)

    async def async_turn_off(self):
        """Turn Off Hot Button."""
        await self.channel.set_hot_button_state(False)


class NavienPowerSwitchEntity(SwitchEntity):
    """Define a Power Switch Entity."""

    def __init__(self, navilink, channel):
        self.navilink = navilink
        self.channel = channel

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self.channel.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self.channel.deregister_callback(self.async_write_ha_state)

    @property
    def available(self):
        """Return if the the device is online or not."""
        return self.channel.is_available()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        return DeviceInfo(
            identifiers = {(DOMAIN, self.navilink.device_info.get("deviceInfo",{}).get("macAddress","unknown") + "_" + str(self.channel.channel_number))},
            manufacturer = "Navien",
            name = self.navilink.device_info.get("deviceInfo",{}).get("deviceName","unknown") + " CH" + str(self.channel.channel_number)
        )

    @property
    def name(self):
        """Return the name of the entity."""
        return self.navilink.device_info.get("deviceInfo",{}).get("deviceName","UNKNOWN") + " Power CH" + str(self.channel.channel_number)


    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return self.navilink.device_info.get("deviceInfo",{}).get("macAddress","unknown") + str(self.channel.channel_number) + "power_button"

    @property
    def is_on(self):
        """Return the current On Demand state."""
        return self.channel.channel_status.get("powerStatus",False)

    async def async_turn_on(self):
        """Turn On Power."""
        await self.channel.set_power_state(True)

    async def async_turn_off(self):
        """Turn Off Power."""
        await self.channel.set_power_state(False)


class MgppAntiLegionellaSwitchEntity(SwitchEntity):
    """Define an MGPP Anti-Legionella Switch Entity."""

    def __init__(self, navilink, channel):
        self.navilink = navilink
        self.channel = channel

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self.channel.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self.channel.deregister_callback(self.async_write_ha_state)

    @property
    def available(self):
        """Return if the the device is online or not."""
        return self.channel.is_available()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        return DeviceInfo(
            identifiers = {(DOMAIN, self.navilink.device_info.get("deviceInfo",{}).get("macAddress","unknown"))},
            manufacturer = "Navien",
            name = self.navilink.device_info.get("deviceInfo",{}).get("deviceName","unknown")
        )

    @property
    def name(self):
        """Return the name of the entity."""
        return self.navilink.device_info.get("deviceInfo",{}).get("deviceName","UNKNOWN") + " Anti-Legionella"

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return self.navilink.device_info.get("deviceInfo",{}).get("macAddress","unknown") + "anti_legionella"

    @property
    def is_on(self):
        """Return the current Anti-Legionella state."""
        # MGPP typically uses 1=off, 2=on for status flags
        return self.channel.channel_status.get("antiLegionellaUse", 0) == 2

    async def async_turn_on(self):
        """Turn On Anti-Legionella."""
        await self.channel.set_anti_legionella_state(True)

    async def async_turn_off(self):
        """Turn Off Anti-Legionella."""
        await self.channel.set_anti_legionella_state(False)


class MgppFreezeProtectionSwitchEntity(SwitchEntity):
    """Define an MGPP Freeze Protection Switch Entity."""

    def __init__(self, navilink, channel):
        self.navilink = navilink
        self.channel = channel

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self.channel.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self.channel.deregister_callback(self.async_write_ha_state)

    @property
    def available(self):
        """Return if the the device is online or not."""
        return self.channel.is_available()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        mac = self.navilink.device_info.get("deviceInfo",{}).get("macAddress","unknown")
        name = self.navilink.device_info.get("deviceInfo",{}).get("deviceName","unknown")
        return DeviceInfo(
            identifiers = {(DOMAIN, mac)},
            manufacturer = "Navien",
            name = name
        )

    @property
    def name(self):
        """Return the name of the entity."""
        return self.navilink.device_info.get("deviceInfo",{}).get("deviceName","UNKNOWN") + " Freeze Protection"

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return self.navilink.device_info.get("deviceInfo",{}).get("macAddress","unknown") + "freeze_protection"

    @property
    def is_on(self):
        """Return the current Freeze Protection state."""
        # MGPP typically uses 1=off, 2=on for status flags
        return self.channel.channel_status.get("freezeProtectionUse", 0) == 2

    async def async_turn_on(self):
        """Turn On Freeze Protection."""
        await self.channel.set_freeze_protection_state(True)

    async def async_turn_off(self):
        """Turn Off Freeze Protection."""
        await self.channel.set_freeze_protection_state(False)