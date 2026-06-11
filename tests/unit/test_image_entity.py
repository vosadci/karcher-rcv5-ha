# SPDX-License-Identifier: MIT
"""Unit tests for KarcherMapImage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

from custom_components.karcher_home_robots.image import KarcherMapImage
from custom_components.karcher_home_robots.map_data import MapGrid, MapSnapshot


def _make_snapshot() -> MapSnapshot:
    grid = MapGrid(
        width=120,
        height=120,
        data=b"\x00" * 3600,
        resolution=0.05,
        min_x=0.0,
        min_y=0.0,
    )
    return MapSnapshot(grid=grid, robot=None, charger=None)


def _make_coordinator(*, map_snapshot: MapSnapshot | None = None) -> MagicMock:
    coordinator = MagicMock()
    coordinator.map_snapshot = map_snapshot
    coordinator.image_last_updated = None
    coordinator.device.device_id = "dev-1"
    coordinator.hass = MagicMock()
    return coordinator


def _make_entity(coordinator: MagicMock | None = None) -> KarcherMapImage:
    if coordinator is None:
        coordinator = _make_coordinator()
    with patch.object(KarcherMapImage, "__init_subclass__", return_value=None):
        entity = KarcherMapImage.__new__(KarcherMapImage)
        # Manually initialise without calling the real HA base class.
        entity.coordinator = coordinator
        entity._attr_content_type = "image/png"
        entity._attr_name = "Map"
        entity._attr_unique_id = f"{coordinator.device.device_id}_map"
        entity.hass = coordinator.hass
        entity._cached_png = None
        entity._cached_snapshot_id = None
    return entity


async def test_async_image_returns_none_when_no_snapshot() -> None:
    entity = _make_entity(_make_coordinator(map_snapshot=None))
    result = await entity.async_image()
    assert result is None


async def test_async_image_returns_bytes_when_snapshot_set() -> None:
    snapshot = _make_snapshot()
    coordinator = _make_coordinator(map_snapshot=snapshot)
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    async def fake_executor(func, *args):  # type: ignore[no-untyped-def]
        return func(*args)

    coordinator.hass.async_add_executor_job = fake_executor
    entity = _make_entity(coordinator)

    with patch(
        "custom_components.karcher_home_robots.image.render_map", return_value=fake_png
    ) as mock_render:
        result = await entity.async_image()

    assert result == fake_png
    mock_render.assert_called_once_with(snapshot, scale=4)


async def test_async_image_uses_cache_on_same_snapshot() -> None:
    snapshot = _make_snapshot()
    coordinator = _make_coordinator(map_snapshot=snapshot)
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    async def fake_executor(func, *args):  # type: ignore[no-untyped-def]
        return func(*args)

    coordinator.hass.async_add_executor_job = fake_executor
    entity = _make_entity(coordinator)

    with patch(
        "custom_components.karcher_home_robots.image.render_map", return_value=fake_png
    ) as mock_render:
        result1 = await entity.async_image()
        result2 = await entity.async_image()

    assert result1 == result2 == fake_png
    mock_render.assert_called_once()  # render only once; second call hits cache


def test_image_last_updated_proxies_coordinator() -> None:
    coordinator = _make_coordinator()
    ts = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
    coordinator.image_last_updated = ts
    entity = _make_entity(coordinator)
    assert entity.image_last_updated == ts


def test_image_last_updated_none_when_no_map() -> None:
    entity = _make_entity(_make_coordinator())
    assert entity.image_last_updated is None


def test_unique_id() -> None:
    entity = _make_entity()
    assert entity._attr_unique_id == "dev-1_map"


def test_content_type() -> None:
    entity = _make_entity()
    assert entity._attr_content_type == "image/png"


async def test_async_setup_entry_registers_entity() -> None:
    from custom_components.karcher_home_robots.image import async_setup_entry

    coordinator = _make_coordinator(map_snapshot=_make_snapshot())
    entry = MagicMock()
    entry.runtime_data = coordinator

    added: list[Any] = []

    def capture(entities: list[Any], **_kwargs: Any) -> None:
        added.extend(entities)

    await async_setup_entry(coordinator.hass, entry, capture)  # type: ignore[arg-type]
    assert len(added) == 1
    assert isinstance(added[0], KarcherMapImage)


async def test_async_image_returns_none_on_render_exception() -> None:
    snapshot = _make_snapshot()
    coordinator = _make_coordinator(map_snapshot=snapshot)

    async def fake_executor(func, *args):  # type: ignore[no-untyped-def]
        return func(*args)

    coordinator.hass.async_add_executor_job = fake_executor
    entity = _make_entity(coordinator)

    with patch(
        "custom_components.karcher_home_robots.image.render_map",
        side_effect=RuntimeError("render failed"),
    ):
        result = await entity.async_image()

    assert result is None
