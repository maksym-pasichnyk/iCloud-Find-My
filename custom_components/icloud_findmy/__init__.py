"""iCloud Find My integration for Home Assistant."""
from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_DEVICE_ID,
    ATTR_MESSAGE,
    ATTR_PHONE_NUMBER,
    DOMAIN,
    SERVICE_LOST_MODE,
    SERVICE_PLAY_SOUND,
    SERVICE_REFRESH,
)
from .coordinator import FindMyCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

PLAY_SOUND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
    }
)

LOST_MODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_MESSAGE, default=""): cv.string,
        vol.Optional(ATTR_PHONE_NUMBER, default=""): cv.string,
    }
)

REFRESH_SCHEMA = vol.Schema({})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iCloud Find My from a config entry."""
    coordinator = FindMyCoordinator(hass, entry)
    try:
        await coordinator.async_setup()
    except Exception as err:
        _LOGGER.error("Failed to initialize iCloud Find My session: %s", err)
        raise

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            # Last entry removed — drop the services too.
            for service in (SERVICE_PLAY_SOUND, SERVICE_LOST_MODE, SERVICE_REFRESH):
                hass.services.async_remove(DOMAIN, service)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry on options update (e.g. scan interval changed)."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services exactly once across all entries."""
    if hass.services.has_service(DOMAIN, SERVICE_PLAY_SOUND):
        return

    def _coordinators() -> list[FindMyCoordinator]:
        return list(hass.data.get(DOMAIN, {}).values())

    def _coordinator_for(device_id: str) -> FindMyCoordinator:
        for coord in _coordinators():
            if coord.data and device_id in coord.data:
                return coord
        # Fallback: caller may have used a serial number we don't track yet.
        if _coordinators():
            return _coordinators()[0]
        raise HomeAssistantError("No iCloud Find My account configured")

    async def play_sound(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        await _coordinator_for(device_id).async_play_sound(device_id)

    async def lost_mode(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        await _coordinator_for(device_id).async_lost_mode(
            device_id,
            call.data.get(ATTR_MESSAGE) or None,
            call.data.get(ATTR_PHONE_NUMBER) or None,
        )

    async def refresh(_call: ServiceCall) -> None:
        for coord in _coordinators():
            await coord.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_PLAY_SOUND, play_sound, schema=PLAY_SOUND_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_LOST_MODE, lost_mode, schema=LOST_MODE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh, schema=REFRESH_SCHEMA)
