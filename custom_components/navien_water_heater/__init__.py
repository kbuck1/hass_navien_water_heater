"""The Navien NaviLink Water Heater Integration."""
from __future__ import annotations
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .navien_api import (
    NavilinkConnect
)
from .const import DOMAIN
import logging
import os
_LOGGER=logging.getLogger(__name__)

PLATFORMS: list[str] = ["water_heater","sensor","switch","binary_sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Navien NaviLink Water Heater Integration from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    aws_path = hass.config.path() 
    subdirs = ['custom_components','navien_water_heater','cert']
    for subdir in subdirs:
        aws_path = os.path.join(aws_path,subdir)
    navilink = NavilinkConnect(userId=entry.data.get("username",""), passwd=entry.data.get("password",""), polling_interval=entry.data.get("polling_interval",15), aws_cert_path=os.path.join(aws_path,"AmazonRootCA1.pem"))
    hass.data[DOMAIN][entry.entry_id] = navilink
    
    # Discover all devices
    device_list = await navilink.start()
    
    # For now, monitor all discovered devices
    # In the future, this could be configurable via config entry options
    mac_addresses = []
    for device_info in device_list:
        mac = device_info.get("deviceInfo",{}).get("macAddress","")
        if mac:
            mac_addresses.append(mac)
    
    if not mac_addresses:
        _LOGGER.error("No devices found to monitor")
        return False
    
    # Connect to MQTT and subscribe to devices
    await navilink.connect_and_subscribe_devices(mac_addresses)
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    navilink = hass.data[DOMAIN][entry.entry_id]
    await navilink.disconnect()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

