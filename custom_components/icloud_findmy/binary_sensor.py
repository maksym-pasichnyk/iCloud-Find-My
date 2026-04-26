"""Binary sensors: online status, low-power mode, locating-in-progress."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import FindMyDevice
from .const import DOMAIN, MANUFACTURER
from .coordinator import FindMyCoordinator


@dataclass(frozen=True, kw_only=True)
class FindMyBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[FindMyDevice], bool | None]


BINARY_SENSORS: tuple[FindMyBinaryDescription, ...] = (
    FindMyBinaryDescription(
        key="online",
        translation_key="online",
        name="Online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda d: d.is_online,
    ),
    FindMyBinaryDescription(
        key="low_power_mode",
        translation_key="low_power_mode",
        name="Low power mode",
        value_fn=lambda d: d.low_power_mode,
    ),
    FindMyBinaryDescription(
        key="locating",
        translation_key="locating",
        name="Locating",
        device_class=BinarySensorDeviceClass.RUNNING,
        # `location_finished == False` means Apple is still trying to locate.
        value_fn=lambda d: (not d.location_finished) if d.location_finished is not None else None,
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
        new: list[FindMyBinary] = []
        for device_id in coordinator.data:
            for desc in BINARY_SENSORS:
                marker = (device_id, desc.key)
                if marker in seen:
                    continue
                seen.add(marker)
                new.append(FindMyBinary(coordinator, device_id, desc))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class FindMyBinary(CoordinatorEntity[FindMyCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    entity_description: FindMyBinaryDescription

    def __init__(
        self,
        coordinator: FindMyCoordinator,
        device_id: str,
        description: FindMyBinaryDescription,
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
        if not super().available or self._device is None:
            return False
        return self.entity_description.value_fn(self._device) is not None

    @property
    def is_on(self) -> bool | None:
        d = self._device
        if d is None:
            return None
        return self.entity_description.value_fn(d)

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
