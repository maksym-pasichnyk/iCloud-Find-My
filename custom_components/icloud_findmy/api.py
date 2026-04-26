"""Thin adapter around the `findmy` library.

This module is the *only* place that imports `findmy`. Every other module in
this integration talks to Apple through `FindMyClient` defined here.

If a future Apple change breaks `findmy`, swap the implementation of
`FindMyClient` (e.g. self-host an anisette server, switch to a different
upstream library, or vendor a forked auth flow) without touching the rest of
the integration.

The methods are all coroutine-friendly: anything blocking is dispatched to an
executor by the caller (the coordinator) so the HA event loop is never
blocked.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)


class FindMyAuthError(Exception):
    """Raised when authentication fails (bad password, revoked token, etc.)."""


class FindMyTwoFactorRequired(Exception):
    """Raised mid-login: caller must collect a 2FA code and call submit_2fa."""


class FindMyConnectionError(Exception):
    """Network / Apple-side transient errors."""


@dataclass
class FindMyDevice:
    """Normalized representation of a Find My device.

    Decoupled from the upstream library's types so the entities never break
    when the upstream model changes shape.
    """

    id: str
    name: str
    model: str | None
    model_display_name: str | None
    raw_model: str | None
    latitude: float | None
    longitude: float | None
    horizontal_accuracy: float | None
    location_timestamp: datetime | None
    location_finished: bool
    battery_level: float | None  # 0..1 (None if unknown)
    battery_status: str | None  # Charging, NotCharging, Unknown, etc.
    low_power_mode: bool | None
    is_online: bool | None
    location_capable: bool
    serial_number: str | None
    raw: dict[str, Any]


class FindMyClient:
    """Adapter around findmy.AppleAccount.

    Lifecycle:
        client = FindMyClient(anisette_url=...)
        await client.async_login(username, password)         # may raise TwoFactorRequired
        await client.async_submit_2fa(code)                  # only if 2FA was raised
        devices = await client.async_fetch_devices()
        session_blob = client.export_session()               # persist for restart
        # later, after restart:
        client = FindMyClient(anisette_url=...)
        client.import_session(session_blob)
        devices = await client.async_fetch_devices()
    """

    def __init__(self, anisette_url: str) -> None:
        self._anisette_url = anisette_url
        self._account = None  # findmy.AppleAccount
        self._anisette = None
        self._pending_2fa_method = None
        self._lock = asyncio.Lock()

    # --- session lifecycle ---------------------------------------------------

    def _ensure_account(self) -> None:
        """Lazily build the AppleAccount + anisette provider in this thread."""
        if self._account is not None:
            return
        # Imported lazily so the module can be imported even before
        # `findmy` has been installed (e.g. during HA pip install).
        from findmy import AppleAccount  # type: ignore[import-not-found]
        from findmy.reports.anisette import RemoteAnisetteProvider  # type: ignore[import-not-found]

        self._anisette = RemoteAnisetteProvider(self._anisette_url)
        self._account = AppleAccount(self._anisette)

    async def async_login(self, username: str, password: str) -> None:
        """Begin login. Raises FindMyTwoFactorRequired if a 2FA code is needed."""
        async with self._lock:
            await asyncio.get_running_loop().run_in_executor(
                None, self._login_blocking, username, password
            )

    def _login_blocking(self, username: str, password: str) -> None:
        from findmy import LoginState  # type: ignore[import-not-found]

        self._ensure_account()
        try:
            state = self._account.login(username, password)
        except Exception as err:  # noqa: BLE001 — upstream raises bare Exception subclasses
            msg = str(err).lower()
            if "password" in msg or "auth" in msg or "401" in msg or "403" in msg:
                raise FindMyAuthError(str(err)) from err
            raise FindMyConnectionError(str(err)) from err

        if state == LoginState.REQUIRE_2FA:
            methods = self._account.get_2fa_methods()
            if not methods:
                raise FindMyAuthError("2FA required but no methods available")
            # Prefer trusted-device prompts; fall back to the first method.
            chosen = next(
                (m for m in methods if "trusted" in type(m).__name__.lower()),
                methods[0],
            )
            chosen.request()
            self._pending_2fa_method = chosen
            raise FindMyTwoFactorRequired()

        if state != LoginState.LOGGED_IN:
            raise FindMyAuthError(f"Unexpected login state: {state}")

    async def async_submit_2fa(self, code: str) -> None:
        """Complete 2FA and finalize the trust token."""
        async with self._lock:
            await asyncio.get_running_loop().run_in_executor(
                None, self._submit_2fa_blocking, code
            )

    def _submit_2fa_blocking(self, code: str) -> None:
        if self._pending_2fa_method is None:
            raise FindMyAuthError("No 2FA challenge in progress")
        try:
            self._pending_2fa_method.submit(code)
        except Exception as err:  # noqa: BLE001
            raise FindMyAuthError(f"2FA submission failed: {err}") from err
        self._pending_2fa_method = None

    # --- session persistence -------------------------------------------------

    def export_session(self) -> str:
        """Return an opaque, base64-encoded session blob.

        Treat as a secret. Storing this means we don't need the password on
        future restarts — Apple's trust token + cookies are enough.
        """
        if self._account is None:
            raise FindMyAuthError("Not logged in")
        data = self._account.export()
        raw = json.dumps(data, default=str).encode()
        return base64.b64encode(raw).decode()

    def import_session(self, blob: str) -> None:
        """Restore a previously exported session."""
        self._ensure_account()
        try:
            data = json.loads(base64.b64decode(blob.encode()))
            self._account.restore(data)
        except Exception as err:  # noqa: BLE001
            raise FindMyAuthError(f"Failed to restore session: {err}") from err

    # --- device data ---------------------------------------------------------

    async def async_fetch_devices(self) -> list[FindMyDevice]:
        """Refresh and return the current list of Find My devices."""
        async with self._lock:
            return await asyncio.get_running_loop().run_in_executor(
                None, self._fetch_devices_blocking
            )

    def _fetch_devices_blocking(self) -> list[FindMyDevice]:
        if self._account is None:
            raise FindMyAuthError("Not logged in")
        try:
            raw_devices = self._account.fetch_devices()
        except Exception as err:  # noqa: BLE001
            msg = str(err).lower()
            if "401" in msg or "auth" in msg or "expired" in msg:
                raise FindMyAuthError(str(err)) from err
            raise FindMyConnectionError(str(err)) from err

        return [self._normalize_device(d) for d in raw_devices]

    @staticmethod
    def _normalize_device(d: Any) -> FindMyDevice:
        """Map findmy's device object onto our stable dataclass."""
        loc = getattr(d, "location", None)
        latitude = getattr(loc, "latitude", None) if loc else None
        longitude = getattr(loc, "longitude", None) if loc else None
        accuracy = getattr(loc, "horizontal_accuracy", None) if loc else None
        ts = getattr(loc, "timestamp", None) if loc else None
        if ts is not None and isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts, tz=timezone.utc)

        battery = getattr(d, "battery_level", None)
        if battery is not None:
            try:
                battery = float(battery)
                # findmy may return either 0..1 or 0..100 depending on version
                if battery > 1:
                    battery = battery / 100.0
            except (TypeError, ValueError):
                battery = None

        return FindMyDevice(
            id=str(getattr(d, "id", None) or getattr(d, "device_id", None) or getattr(d, "name", "")),
            name=str(getattr(d, "name", "Unknown")),
            model=getattr(d, "device_class", None) or getattr(d, "device_model", None),
            model_display_name=getattr(d, "device_display_name", None),
            raw_model=getattr(d, "raw_device_model", None),
            latitude=latitude,
            longitude=longitude,
            horizontal_accuracy=accuracy,
            location_timestamp=ts,
            location_finished=bool(getattr(loc, "is_finished", True)) if loc else True,
            battery_level=battery,
            battery_status=getattr(d, "battery_status", None),
            low_power_mode=getattr(d, "low_power_mode", None),
            is_online=getattr(d, "is_online", None),
            location_capable=bool(getattr(d, "location_capable", True)),
            serial_number=getattr(d, "serial_number", None),
            raw={},  # populated by caller if useful for debugging
        )

    # --- actions -------------------------------------------------------------

    async def async_play_sound(self, device_id: str) -> None:
        async with self._lock:
            await asyncio.get_running_loop().run_in_executor(
                None, self._play_sound_blocking, device_id
            )

    def _play_sound_blocking(self, device_id: str) -> None:
        device = self._find_device(device_id)
        try:
            device.play_sound()
        except Exception as err:  # noqa: BLE001
            raise FindMyConnectionError(f"play_sound failed: {err}") from err

    async def async_lost_mode(
        self,
        device_id: str,
        message: str | None = None,
        phone_number: str | None = None,
    ) -> None:
        async with self._lock:
            await asyncio.get_running_loop().run_in_executor(
                None, self._lost_mode_blocking, device_id, message, phone_number
            )

    def _lost_mode_blocking(
        self,
        device_id: str,
        message: str | None,
        phone_number: str | None,
    ) -> None:
        device = self._find_device(device_id)
        try:
            device.lost_mode(message=message or "", phone_number=phone_number or "")
        except Exception as err:  # noqa: BLE001
            raise FindMyConnectionError(f"lost_mode failed: {err}") from err

    def _find_device(self, device_id: str):
        if self._account is None:
            raise FindMyAuthError("Not logged in")
        for d in self._account.fetch_devices():
            if str(getattr(d, "id", None) or getattr(d, "device_id", None)) == device_id:
                return d
            if str(getattr(d, "name", "")) == device_id:
                return d
        raise FindMyConnectionError(f"Device {device_id!r} not found")
