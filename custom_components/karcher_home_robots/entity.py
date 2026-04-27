# SPDX-License-Identifier: MIT
"""Shared entity base — device_info, coordinator binding, availability.

All platform entities inherit from KarcherEntity (spec/04 §4.3).
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._types import DeviceProperties
from .const import DOMAIN
from .coordinator import KarcherCoordinator


class KarcherEntity(CoordinatorEntity[KarcherCoordinator]):
    """Base entity for all Kärcher Home Robots platform entities.

    Provides:
      - device_info: groups all entities under the robot device
      - _attr_has_entity_name = True: entity names are composed from
        the device name + the entity translation_key
      - available: True when last_update_success and data is present
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry info shared by all entities of this robot."""
        device = self.coordinator._device
        return DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.nickname or device.sn,
            manufacturer="Kärcher",
            model="RCV5",
            serial_number=device.sn,
        )

    @property
    def available(self) -> bool:
        """Return True when the coordinator has data and last update succeeded."""
        return super().available and self.coordinator.data is not None

    @property
    def _data(self) -> DeviceProperties | None:
        """Return coordinator data as Optional for None-safe access in subclasses.

        DataUpdateCoordinator's stub types .data as non-Optional, but it can
        be None before the first successful refresh. This property re-exposes
        it as Optional so subclass None checks are not flagged as unreachable.
        """
        data: DeviceProperties | None = self.coordinator.data
        return data
