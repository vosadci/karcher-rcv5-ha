# SPDX-License-Identifier: MIT
"""Shared entity base — device_info, coordinator binding, availability."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._types import DeviceProperties
from .const import DOMAIN
from .coordinator import KarcherCoordinator


class KarcherEntity(CoordinatorEntity[KarcherCoordinator]):
    """Base entity for all Kärcher Home Robots platform entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        device = self.coordinator.device
        return DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.nickname or device.sn,
            manufacturer="Kärcher",
            model="RCV5",
            serial_number=device.sn,
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def _data(self) -> DeviceProperties | None:
        # DataUpdateCoordinator stubs .data as non-Optional, but it is None
        # before the first successful refresh. Re-typed here so subclass None
        # checks are not flagged as unreachable by mypy.
        data: DeviceProperties | None = self.coordinator.data
        return data
