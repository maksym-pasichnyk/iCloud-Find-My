"""Config + options flow for iCloud Find My."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .api import (
    FindMyAuthError,
    FindMyClient,
    FindMyConnectionError,
    FindMyTwoFactorRequired,
)
from .const import (
    CONF_2FA_CODE,
    CONF_ANISETTE_URL,
    CONF_SCAN_INTERVAL,
    CONF_SESSION,
    DEFAULT_ANISETTE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_ANISETTE_URL, default=DEFAULT_ANISETTE_URL): str,
    }
)

TWOFA_SCHEMA = vol.Schema({vol.Required(CONF_2FA_CODE): str})


class FindMyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the user-facing setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._client: FindMyClient | None = None
        self._username: str | None = None
        self._anisette_url: str = DEFAULT_ANISETTE_URL
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._anisette_url = user_input.get(CONF_ANISETTE_URL, DEFAULT_ANISETTE_URL)
            self._client = FindMyClient(anisette_url=self._anisette_url)

            await self.async_set_unique_id(self._username.lower())
            if not self._reauth_entry:
                self._abort_if_unique_id_configured()

            try:
                await self._client.async_login(
                    self._username, user_input[CONF_PASSWORD]
                )
            except FindMyTwoFactorRequired:
                return await self.async_step_twofa()
            except FindMyAuthError as err:
                _LOGGER.debug("Auth error: %s", err)
                errors["base"] = "invalid_auth"
            except FindMyConnectionError as err:
                _LOGGER.debug("Connection error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during login")
                errors["base"] = "unknown"
            else:
                # No 2FA needed (rare for Apple IDs nowadays) — finalize.
                return await self._async_finish_login()

        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors=errors,
            description_placeholders={"anisette_default": DEFAULT_ANISETTE_URL},
        )

    async def async_step_twofa(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._client is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._client.async_submit_2fa(user_input[CONF_2FA_CODE])
            except FindMyAuthError as err:
                _LOGGER.debug("2FA failed: %s", err)
                errors["base"] = "invalid_2fa"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during 2FA")
                errors["base"] = "unknown"
            else:
                return await self._async_finish_login()

        return self.async_show_form(
            step_id="twofa", data_schema=TWOFA_SCHEMA, errors=errors
        )

    async def _async_finish_login(self) -> ConfigFlowResult:
        assert self._client is not None
        try:
            session = await self.hass.async_add_executor_job(
                self._client.export_session
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Could not export session")
            raise HomeAssistantError("Could not save iCloud session") from err

        data = {
            CONF_USERNAME: self._username,
            CONF_ANISETTE_URL: self._anisette_url,
            CONF_SESSION: session,
        }

        if self._reauth_entry is not None:
            self.hass.config_entries.async_update_entry(self._reauth_entry, data=data)
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        return self.async_create_entry(title=self._username or "iCloud Find My", data=data)

    # --- reauth path ---------------------------------------------------------

    async def async_step_reauth(
        self, _entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()

    # --- options flow --------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlow:
        return FindMyOptionsFlow(config_entry)


class FindMyOptionsFlow(OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.entry.options.get(
            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=int(MIN_SCAN_INTERVAL.total_seconds()))
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
