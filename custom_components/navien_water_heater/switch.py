"""Support for Navien NaviLink water heaters On Demand/External Recirculator."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import NavienBaseEntity
from .migration import get_legacy_unique_id_if_exists
from .navien_api import MgppDevice
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Navien On Demand switch based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    
    for device in coordinator.devices.values():
        if isinstance(device, MgppDevice):
            # MGPP-specific switches
            entities.append(MgppAntiLegionellaSwitchEntity(device))
            entities.append(MgppFreezeProtectionSwitchEntity(device))
        else:
            # Legacy switches
            if device.channel_info.get("onDemandUse", 2) == 1:
                entities.append(NavienOnDemandSwitchEntity(device))
            entities.append(NavienPowerSwitchEntity(device))
    
    async_add_entities(entities)


class NavienOnDemandSwitchEntity(NavienBaseEntity, SwitchEntity):
    """Define a Navien Hot Button/On Demand/External Recirculator Entity."""

    _attr_name = "Hot Button"

    def __init__(self, device):
        """Initialize the entity."""
        super().__init__(device)
        self._cached_unique_id = None

    def _get_legacy_unique_id(self) -> str:
        """Return legacy unique_id format: {mac}{channel}hot_button"""
        return f"{self._device.mac_address}{self._device.channel_number}hot_button"

    def _get_new_unique_id(self) -> str:
        """Return new unique_id format: {mac}_{channel}_hot_button"""
        return f"{self._device.device_identifier}_hot_button"

    @property
    def unique_id(self):
        """Return the unique ID of the entity, using legacy format if it exists."""
        if self._cached_unique_id is not None:
            return self._cached_unique_id
        
        if self.hass is None:
            return self._get_new_unique_id()
        
        self._cached_unique_id = get_legacy_unique_id_if_exists(
            self.hass, "switch",
            self._get_legacy_unique_id(),
            self._get_new_unique_id(),
        )
        return self._cached_unique_id

    @property
    def is_on(self):
        """Return the current On Demand state."""
        return self._device.channel_status.get("onDemandUseFlag", False)

    async def async_turn_on(self):
        """Turn On Hot Button."""
        await self._device.set_hot_button_state(True)

    async def async_turn_off(self):
        """Turn Off Hot Button."""
        await self._device.set_hot_button_state(False)


class NavienPowerSwitchEntity(NavienBaseEntity, SwitchEntity):
    """Define a Power Switch Entity."""

    _attr_name = "Power"

    def __init__(self, device):
        """Initialize the entity."""
        super().__init__(device)
        self._cached_unique_id = None

    def _get_legacy_unique_id(self) -> str:
        """Return legacy unique_id format: {mac}{channel}power_button"""
        return f"{self._device.mac_address}{self._device.channel_number}power_button"

    def _get_new_unique_id(self) -> str:
        """Return new unique_id format: {mac}_{channel}_power"""
        return f"{self._device.device_identifier}_power"

    @property
    def unique_id(self):
        """Return the unique ID of the entity, using legacy format if it exists."""
        if self._cached_unique_id is not None:
            return self._cached_unique_id
        
        if self.hass is None:
            return self._get_new_unique_id()
        
        self._cached_unique_id = get_legacy_unique_id_if_exists(
            self.hass, "switch",
            self._get_legacy_unique_id(),
            self._get_new_unique_id(),
        )
        return self._cached_unique_id

    @property
    def is_on(self):
        """Return the current power state."""
        return self._device.channel_status.get("powerStatus", False)

    async def async_turn_on(self):
        """Turn On Power."""
        await self._device.set_power_state(True)

    async def async_turn_off(self):
        """Turn Off Power."""
        await self._device.set_power_state(False)


class MgppAntiLegionellaSwitchEntity(NavienBaseEntity, SwitchEntity):
    """Define an MGPP Anti-Legionella Switch Entity."""

    _attr_name = "Anti-Legionella"

    def __init__(self, device):
        """Initialize the entity."""
        super().__init__(device)
        self._cached_unique_id = None

    def _get_legacy_unique_id(self) -> str:
        """Return legacy unique_id format: {mac}anti_legionella"""
        return f"{self._device.mac_address}anti_legionella"

    def _get_new_unique_id(self) -> str:
        """Return new unique_id format: {mac}_anti_legionella"""
        return f"{self._device.device_identifier}_anti_legionella"

    @property
    def unique_id(self):
        """Return the unique ID of the entity, using legacy format if it exists."""
        if self._cached_unique_id is not None:
            return self._cached_unique_id
        
        if self.hass is None:
            return self._get_new_unique_id()
        
        self._cached_unique_id = get_legacy_unique_id_if_exists(
            self.hass, "switch",
            self._get_legacy_unique_id(),
            self._get_new_unique_id(),
        )
        return self._cached_unique_id

    @property
    def is_on(self):
        """Return the current Anti-Legionella state."""
        # MGPP typically uses 1=off, 2=on for status flags
        return self._device.channel_status.get("antiLegionellaUse", 0) == 2

    async def async_turn_on(self):
        """Turn On Anti-Legionella."""
        await self._device.set_anti_legionella_state(True)

    async def async_turn_off(self):
        """Turn Off Anti-Legionella."""
        await self._device.set_anti_legionella_state(False)


class MgppFreezeProtectionSwitchEntity(NavienBaseEntity, SwitchEntity):
    """Define an MGPP Freeze Protection Switch Entity."""

    _attr_name = "Freeze Protection"

    def __init__(self, device):
        """Initialize the entity."""
        super().__init__(device)
        self._cached_unique_id = None

    def _get_legacy_unique_id(self) -> str:
        """Return legacy unique_id format: {mac}freeze_protection"""
        return f"{self._device.mac_address}freeze_protection"

    def _get_new_unique_id(self) -> str:
        """Return new unique_id format: {mac}_freeze_protection"""
        return f"{self._device.device_identifier}_freeze_protection"

    @property
    def unique_id(self):
        """Return the unique ID of the entity, using legacy format if it exists."""
        if self._cached_unique_id is not None:
            return self._cached_unique_id
        
        if self.hass is None:
            return self._get_new_unique_id()
        
        self._cached_unique_id = get_legacy_unique_id_if_exists(
            self.hass, "switch",
            self._get_legacy_unique_id(),
            self._get_new_unique_id(),
        )
        return self._cached_unique_id

    @property
    def is_on(self):
        """Return the current Freeze Protection state."""
        # MGPP typically uses 1=off, 2=on for status flags
        return self._device.channel_status.get("freezeProtectionUse", 0) == 2

    async def async_turn_on(self):
        """Turn On Freeze Protection."""
        await self._device.set_freeze_protection_state(True)

    async def async_turn_off(self):
        """Turn Off Freeze Protection."""
        await self._device.set_freeze_protection_state(False)
