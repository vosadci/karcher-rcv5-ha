"""Base entity for Kärcher Home Robots."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KarcherCoordinator


class KarcherEntity(CoordinatorEntity[KarcherCoordinator]):
    """Base class for all Kärcher entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        dev = coordinator.device
        self._attr_unique_id = dev.device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dev.device_id)},
            name=dev.nickname,
            manufacturer="Kärcher",
            model=dev.product_id.name if dev.product_id else None,
            serial_number=dev.sn,
        )
