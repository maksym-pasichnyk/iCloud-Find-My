"""DataUpdateCoordinator: polls Find My on a schedule and exposes devices."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    FindMyAuthError,
    FindMyClient,
    FindMyConnectionError,
    FindMyDevice,
)
from .const import (
    CONF_ANISETTE_URL,
    CONF_SCAN_INTERVAL,
    CONF_SESSION,
    DEFAULT_ANISETTE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class FindMyCoordinator(DataUpdateCoordinator[dict[str, FindMyDevice]]):
    """Polls iCloud Find My and indexes devices by id."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL)
        interval = (
            timedelta(seconds=int(scan_interval))
            if scan_interval
            else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({entry.title})",
            update_interval=interval,
        )
        self.entry = entry
        self.client = FindMyClient(
            anisette_url=entry.data.get(CONF_ANISETTE_URL, DEFAULT_ANISETTE_URL)
        )
        self._restored = False

    async def async_setup(self) -> None:
        """Restore the saved session before the first refresh."""
        session = self.entry.data.get(CONF_SESSION)
        if not session:
            raise UpdateFailed(
                "No saved iCloud session — re-add the integration to log in again."
            )
        await self.hass.async_add_executor_job(self.client.import_session, session)
        self._restored = True

    async def _async_update_data(self) -> dict[str, FindMyDevice]:
        if not self._restored:
            await self.async_setup()
        try:
            devices = await self.client.async_fetch_devices()
        except FindMyAuthError as err:
            # Tell HA to start the reauth flow — the user will need to re-enter
            # 2FA. We surface this as ConfigEntryAuthFailed via UpdateFailed so
            # the entries reload path picks it up.
            raise UpdateFailed(f"Authentication failed, re-auth required: {err}") from err
        except FindMyConnectionError as err:
            raise UpdateFailed(f"Could not reach iCloud: {err}") from err

        # Persist any session changes (rotated cookies, etc.) so we don't have
        # to re-login after a restart.
        try:
            new_session = await self.hass.async_add_executor_job(
                self.client.export_session
            )
            if new_session and new_session != self.entry.data.get(CONF_SESSION):
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={**self.entry.data, CONF_SESSION: new_session},
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not persist refreshed session: %s", err)

        return {d.id: d for d in devices}

    # --- service helpers -----------------------------------------------------

    async def async_play_sound(self, device_id: str) -> None:
        await self.client.async_play_sound(device_id)

    async def async_lost_mode(
        self,
        device_id: str,
        message: str | None,
        phone_number: str | None,
    ) -> None:
        await self.client.async_lost_mode(device_id, message, phone_number)
