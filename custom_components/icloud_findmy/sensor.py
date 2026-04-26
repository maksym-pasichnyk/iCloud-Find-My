"""Sensor platform: battery level, last-seen timestamp, battery status."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import FindMyDevice
from .const import DOMAIN, MANUFACTURER
from .coordinator import FindMyCoordinator


@dataclass(frozen=True, kw_only=True)
class FindMySensorDescription(SensorEntityDescription):
    """Describe a sensor and how to compute its value from a device."""

    value_fn: Callable[[FindMyDevice], Any]


SENSORS: tuple[FindMySensorDescription, ...] = (
    FindMySensorDescription(
        key="battery_level",
        translation_key="battery_level",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: int(round(d.battery_level * 100))
        if d.battery_level is not None
        else None,
    ),
    FindMySensorDescription(
        key="last_seen",
        translation_key="last_seen",
        name="Last seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.location_timestamp,
    ),
    FindMySensorDescription(
        key="battery_status",
        translation_key="battery_status",
        name="Battery status",
        value_fn=lambda d: d.battery_status,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FindMyCoordinator = hass.data[DOMAIN][entry.entry_id]
    seen: set[tuple[str, str]] = set()

    @callback
    def _add_new() -> None:
        new: list[FindMySensor] = []
        for device_id in coordinator.data:
            for desc in SENSORS:
                marker = (device_id, desc.key)
                if marker in seen:
                    continue
                seen.add(marker)
                new.append(FindMySensor(coordinator, device_id, desc))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class FindMySensor(CoordinatorEntity[FindMyCoordinator], SensorEntity):
    """Generic sensor driven by a SensorEntityDescription."""

    _attr_has_entity_name = True
    entity_description: FindMySensorDescription

    def __init__(
        self,
        coordinator: FindMyCoordinator,
        device_id: str,
        description: FindMySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._device_id = device_id
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{device_id}_{description.key}"
        )

    @property
    def _device(self) -> FindMyDevice | None:
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        return super().available and self._device is not None

    @property
    def native_value(self) -> Any:
        d = self._device
        if d is None:
            return None
        try:
            value = self.entity_description.value_fn(d)
        except Exception:  # noqa: BLE001 — defensive against upstream None values
            return None
        # Timestamps must be tz-aware for SensorDeviceClass.TIMESTAMP.
        if isinstance(value, datetime) and value.tzinfo is None:
            return None
        return value

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
