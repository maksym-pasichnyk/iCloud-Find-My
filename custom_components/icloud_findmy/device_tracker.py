"""device_tracker platform: one TrackerEntity per Find My device."""
from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import FindMyDevice
from .const import DOMAIN, MANUFACTURER
from .coordinator import FindMyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FindMyCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = []
        for device_id, device in coordinator.data.items():
            if device_id in known:
                continue
            if not device.location_capable:
                # Skip accessories that cannot report location (e.g. Beats).
                continue
            known.add(device_id)
            new.append(FindMyTracker(coordinator, device_id))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class FindMyTracker(CoordinatorEntity[FindMyCoordinator], TrackerEntity):
    """Location tracker for a single Find My device."""

    _attr_has_entity_name = True
    _attr_name = None  # let HA use the device name as the entity name

    def __init__(self, coordinator: FindMyCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{device_id}_tracker"

    @property
    def _device(self) -> FindMyDevice | None:
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        return super().available and self._device is not None

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        d = self._device
        return d.latitude if d else None

    @property
    def longitude(self) -> float | None:
        d = self._device
        return d.longitude if d else None

    @property
    def location_accuracy(self) -> float:
        d = self._device
        if d and d.horizontal_accuracy is not None:
            return float(d.horizontal_accuracy)
        return 0.0

    @property
    def battery_level(self) -> int | None:
        d = self._device
        if d and d.battery_level is not None:
            return int(round(d.battery_level * 100))
        return None

    @property
    def device_info(self) -> DeviceInfo:
        d = self._device
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=d.name if d else self._device_id,
            manufacturer=MANUFACTURER,
            model=(d.model_display_name or d.model) if d else None,
            serial_number=d.serial_number if d else None,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._device
        if d is None:
            return {}
        return {
            "last_seen": d.location_timestamp.isoformat() if d.location_timestamp else None,
            "location_finished": d.location_finished,
            "battery_status": d.battery_status,
            "low_power_mode": d.low_power_mode,
            "is_online": d.is_online,
            "raw_model": d.raw_model,
            "device_id": d.id,
        }
