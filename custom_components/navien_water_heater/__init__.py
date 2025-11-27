"""The Navien NaviLink Water Heater Integration."""
from __future__ import annotations
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from .navien_api import NavilinkAccountCoordinator
from .const import DOMAIN
import logging
import os

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["water_heater", "sensor", "switch", "binary_sensor", "number"]


def _get_disabled_device_identifiers(hass: HomeAssistant) -> set[str]:
    """Get the set of Navien device identifiers that are disabled in the device registry."""
    disabled_identifiers = set()
    device_registry = dr.async_get(hass)
    
    for device in device_registry.devices.values():
        # Check if this is a Navien device
        for domain, identifier in device.identifiers:
            if domain == DOMAIN and device.disabled_by is not None:
                disabled_identifiers.add(identifier)
    
    return disabled_identifiers


def _sync_disabled_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Sync disabled devices from HA device registry to the coordinator."""
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator is None:
        return
    
    disabled_identifiers = _get_disabled_device_identifiers(hass)
    coordinator.set_disabled_devices(disabled_identifiers)
    _LOGGER.debug(f"Synced disabled devices to coordinator: {disabled_identifiers}")


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to new version."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        # Version 1 -> 2: Remove device_index, now we expose all devices
        new_data = {**config_entry.data}
        new_data.pop("device_index", None)

        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            version=2
        )
        _LOGGER.info("Migration to version 2 successful: removed device_index")

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Navien NaviLink Water Heater Integration from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    
    # Build path to AWS certificate
    aws_path = hass.config.path()
    subdirs = ['custom_components', 'navien_water_heater', 'cert']
    for subdir in subdirs:
        aws_path = os.path.join(aws_path, subdir)

    # Create the account coordinator
    coordinator = NavilinkAccountCoordinator(
        userId=entry.data.get("username", ""),
        passwd=entry.data.get("password", ""),
        polling_interval=entry.data.get("polling_interval", 15),
        aws_cert_path=os.path.join(aws_path, "AmazonRootCA1.pem")
    )
    
    # Store coordinator in hass data
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    # Start the coordinator (connects to all gateways)
    await coordinator.start()
    
    # Forward setup to all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Sync disabled devices from device registry after platforms are set up
    _sync_disabled_devices(hass, entry)
    
    # Listen for device registry changes to update polling state
    @callback
    def async_device_registry_updated(event) -> None:
        """Handle device registry updates."""
        if event.data.get("action") == "update":
            # Re-sync disabled devices when a device is updated
            _sync_disabled_devices(hass, entry)
    
    entry.async_on_unload(
        hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, async_device_registry_updated)
    )
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.disconnect()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
