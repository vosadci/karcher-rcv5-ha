# SPDX-License-Identifier: MIT
"""Integration tests for config entry migration.

Covers: FR-MG-2, FR-MG-3, FR-MG-4, FR-MG-5, FR-MG-5a
"""

from __future__ import annotations

from unittest.mock import patch

from custom_components.karcher_home_robots.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import TEST_DEVICE
from tests.integration.test_init_lifecycle import FakeAdapter, _patch_adapter

# v1 entry data — same shape as the legacy integration before v2.
_V1_DATA = {
    "region": "eu",
    "email": "test@example.com",
    "password": "secret",
    "device_id": TEST_DEVICE.device_id,
    "sn": TEST_DEVICE.sn,
    "product_id": TEST_DEVICE.product_id,
    "nickname": TEST_DEVICE.nickname,
}


def _make_v1_entry(**kwargs: object) -> MockConfigEntry:
    data = {**_V1_DATA, **kwargs}
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        unique_id=data["device_id"],  # type: ignore[arg-type]
        version=1,
    )


# ---------------------------------------------------------------------------
# FR-MG-2: v1 → v2 adds region_endpoint_snapshot
# ---------------------------------------------------------------------------


async def test_migration_v1_to_v2_adds_snapshot(hass: HomeAssistant) -> None:
    """Migration bumps version to 2 and adds region_endpoint_snapshot.

    Covers: FR-MG-2
    """
    entry = _make_v1_entry()
    entry.add_to_hass(hass)
    assert entry.version == 1
    assert "region_endpoint_snapshot" not in entry.data

    fake = FakeAdapter()
    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.version == 3
    assert "region_endpoint_snapshot" in entry.data


async def test_migration_v1_to_v2_preserves_existing_fields(hass: HomeAssistant) -> None:
    """Migration does not drop pre-existing data fields.

    Covers: FR-MG-2
    """
    entry = _make_v1_entry()
    entry.add_to_hass(hass)

    fake = FakeAdapter()
    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.data["region"] == "eu"
    assert entry.data["email"] == "test@example.com"
    assert entry.data["device_id"] == TEST_DEVICE.device_id


async def test_migration_v1_already_has_snapshot(hass: HomeAssistant) -> None:
    """If v1 entry somehow has region_endpoint_snapshot, migration does not duplicate it."""
    snapshot = {"rest_base_url": "https://eu.example.com", "mqtt_url": None}
    entry = _make_v1_entry(region_endpoint_snapshot=snapshot)
    entry.add_to_hass(hass)

    fake = FakeAdapter()
    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.version == 3
    # After setup the snapshot is updated to what the adapter returned
    assert "region_endpoint_snapshot" in entry.data


# ---------------------------------------------------------------------------
# FR-MG-3: entity unique_id re-keying
# ---------------------------------------------------------------------------


async def test_migration_rekeys_legacy_unique_ids(hass: HomeAssistant) -> None:
    """Legacy unique_ids are re-keyed to canonical {device_id}_{entity_type}.

    Covers: FR-MG-3
    """
    entry = _make_v1_entry()
    entry.add_to_hass(hass)

    # Register a fake legacy entity with a non-canonical unique_id.
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "vacuum",
        DOMAIN,
        "old_prefix_vacuum",  # legacy form
        config_entry=entry,
        suggested_object_id="test_robot_vacuum",
    )

    fake = FakeAdapter()
    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # The entity should now carry the canonical unique_id.
    canonical = f"{TEST_DEVICE.device_id}_vacuum"
    entity = ent_reg.async_get_entity_id("vacuum", DOMAIN, canonical)
    assert entity is not None, f"No entity found with unique_id {canonical!r}"


async def test_migration_leaves_already_canonical_unique_ids(hass: HomeAssistant) -> None:
    """Entities already using canonical unique_ids are left untouched.

    Covers: FR-MG-3
    """
    entry = _make_v1_entry()
    entry.add_to_hass(hass)

    ent_reg = er.async_get(hass)
    canonical_uid = f"{TEST_DEVICE.device_id}_battery"
    ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        canonical_uid,
        config_entry=entry,
        suggested_object_id="test_robot_battery",
    )

    fake = FakeAdapter()
    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Entity should still be there with the same canonical unique_id.
    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, canonical_uid)
    assert entity_id is not None


# ---------------------------------------------------------------------------
# FR-MG-4: upgrade test — v1 → v2, entities survive
# ---------------------------------------------------------------------------


async def test_upgrade_v1_to_v2_entities_survive(hass: HomeAssistant) -> None:
    """Full upgrade: v1 entry migrates and entities remain resolvable.

    Covers: FR-MG-4
    """
    entry = _make_v1_entry()
    entry.add_to_hass(hass)

    # Pre-register canonical entities as if they were created by the v1 integration.
    ent_reg = er.async_get(hass)
    device_id = TEST_DEVICE.device_id
    pre_registered = {
        "vacuum": ent_reg.async_get_or_create(
            "vacuum",
            DOMAIN,
            f"{device_id}_vacuum",
            config_entry=entry,
            suggested_object_id="test_robot_vacuum",
        ),
        "battery": ent_reg.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{device_id}_battery",
            config_entry=entry,
            suggested_object_id="test_robot_battery",
        ),
    }

    fake = FakeAdapter()
    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.version == 3
    # Entities resolve to the same entity_ids after migration.
    for platform, reg_entry in pre_registered.items():
        entity_id = ent_reg.async_get_entity_id(
            platform if platform != "battery" else "sensor",
            DOMAIN,
            reg_entry.unique_id,
        )
        assert entity_id is not None, f"Entity {platform} lost its entity_id after migration"


# ---------------------------------------------------------------------------
# FR-MG-5, FR-MG-5a: migration failure → False + repair issue
# ---------------------------------------------------------------------------


async def test_migration_failure_returns_false_and_creates_repair(
    hass: HomeAssistant,
) -> None:
    """When migration raises, async_migrate_entry returns False and creates repair issue.

    Covers: FR-MG-5, FR-MG-5a
    """
    entry = _make_v1_entry()
    entry.add_to_hass(hass)

    fake = FakeAdapter()
    with (
        _patch_adapter(fake),
        patch(
            "custom_components.karcher_home_robots._migrate_v1_to_v2",
            side_effect=RuntimeError("simulated migration failure"),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Entry should have failed to load.
    assert entry.state in (ConfigEntryState.SETUP_ERROR, ConfigEntryState.MIGRATION_ERROR)

    # A repair issue should have been created.
    issue_reg = ir.async_get(hass)
    issue_id = f"migration_failed_v1_v2_{entry.entry_id}"
    issue = issue_reg.async_get_issue(DOMAIN, issue_id)
    assert issue is not None, "Repair issue was not created after migration failure"
    assert issue.severity == ir.IssueSeverity.ERROR


# ---------------------------------------------------------------------------
# v2 → v3: sn/product_id/nickname removed
# ---------------------------------------------------------------------------

_V2_DATA = {
    "region": "eu",
    "email": "test@example.com",
    "password": "secret",
    "device_id": TEST_DEVICE.device_id,
    "sn": TEST_DEVICE.sn,
    "product_id": TEST_DEVICE.product_id,
    "nickname": TEST_DEVICE.nickname,
    "region_endpoint_snapshot": {},
}


def _make_v2_entry(**kwargs: object) -> MockConfigEntry:
    data = {**_V2_DATA, **kwargs}
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        unique_id=data["device_id"],  # type: ignore[arg-type]
        version=2,
    )


async def test_migration_v2_to_v3_removes_redundant_fields(hass: HomeAssistant) -> None:
    """v2 → v3 strips sn, product_id, nickname from entry data."""
    entry = _make_v2_entry()
    entry.add_to_hass(hass)

    fake = FakeAdapter()
    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.version == 3
    assert "sn" not in entry.data
    assert "product_id" not in entry.data
    assert "nickname" not in entry.data


async def test_migration_v2_to_v3_preserves_required_fields(hass: HomeAssistant) -> None:
    """v2 → v3 keeps region, email, password, device_id, region_endpoint_snapshot."""
    entry = _make_v2_entry()
    entry.add_to_hass(hass)

    fake = FakeAdapter()
    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.data["region"] == "eu"
    assert entry.data["email"] == "test@example.com"
    assert entry.data["device_id"] == TEST_DEVICE.device_id


async def test_migration_v1_chains_to_v3(hass: HomeAssistant) -> None:
    """v1 → v2 → v3 chained: entry reaches version 3 with redundant fields removed."""
    entry = _make_v1_entry()
    entry.add_to_hass(hass)

    fake = FakeAdapter()
    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.version == 3
    assert "sn" not in entry.data
    assert "product_id" not in entry.data
    assert "nickname" not in entry.data
    assert "region_endpoint_snapshot" in entry.data
