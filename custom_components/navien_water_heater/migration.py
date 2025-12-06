"""Migration utilities for backward compatibility with legacy entity unique_ids."""
import logging
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)


def get_legacy_unique_id_if_exists(
    hass: HomeAssistant,
    domain: str,
    legacy_unique_id: str,
    new_unique_id: str,
) -> str:
    """Return the legacy unique_id if it exists in the entity registry, otherwise return the new one.
    
    This enables backward compatibility when unique_id formats change. If an entity
    was previously registered with the old format, we continue using it to preserve
    entity_id, history, and automation references.
    
    Args:
        hass: Home Assistant instance
        domain: Entity domain (e.g., "sensor", "switch", "water_heater")
        legacy_unique_id: The old unique_id format
        new_unique_id: The new unique_id format
        
    Returns:
        The legacy_unique_id if an entity with that ID exists, otherwise new_unique_id
    """
    registry = er.async_get(hass)
    
    # Check if an entity with the legacy unique_id exists
    if registry.async_get_entity_id(domain, "navien_water_heater", legacy_unique_id):
        _LOGGER.debug(
            "Using legacy unique_id %s (entity exists in registry)",
            legacy_unique_id
        )
        return legacy_unique_id
    
    return new_unique_id
