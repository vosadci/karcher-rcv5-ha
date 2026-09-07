# SPDX-License-Identifier: MIT
"""What a model's support tier actually does for the user.

The tier gates nothing — every model gets the full entity set — so its whole
effect is here: which models prompt for a report, and what the integration
records when an unverified one reports a value our tables do not describe.

Assertions go through the issue registry — what the user actually sees — never
through a coordinator field. The negative cases carry the weight. Prompting on
EXPECTED would reach most new users and teach them to dismiss repairs, which
would cost us the two prompts that matter; a test that only checks the prompts
fire would not notice that regression.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from custom_components.karcher_home_robots._model_profile import (
    SupportTier,
    repair_key_for_tier,
)
from custom_components.karcher_home_robots.adapter import Device
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.coordinator import (
    _MODEL_SUPPORT_REPAIR_KEYS,
    KarcherCoordinator,
)
from custom_components.karcher_home_robots.map_data import (
    MapGrid,
    MapSnapshot,
    RestrictedZone,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.issue_registry import IssueSeverity
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import TEST_DEVICE, make_entry, make_props

_UNCERTAIN = "model_support_uncertain"
_UNLISTED = "model_support_unlisted"


def _coord(
    hass: HomeAssistant, device: Device, entry: MockConfigEntry | None = None
) -> KarcherCoordinator:
    """One coordinator for `device`.

    `entry` is reusable on purpose. Repair issue IDs are scoped by config-entry
    ID, so a "restart with a new tier" test that builds a fresh entry addresses a
    different issue and silently proves nothing — it was written that way first
    and a mutant that never cleared the stale repair survived it.
    """
    if entry is None:
        entry = make_entry()
        entry.add_to_hass(hass)
    return KarcherCoordinator(hass, MagicMock(), device, config_entry=entry)


def _device(tier: SupportTier | None, *, model: str = "RVF 7", pid: str = "1950097634462887936"):
    return replace(TEST_DEVICE, product_id=pid, model=model, support_tier=tier)


def _issue(coord: KarcherCoordinator, key: str) -> ir.IssueEntry | None:
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    return ir.async_get(coord.hass).async_get_issue(DOMAIN, f"{key}_{entry_id}")


def _raised(coord: KarcherCoordinator) -> set[str]:
    """Which model-support repairs the user is currently being shown.

    Scans the literals above rather than the production tuple: a helper that
    looks only where the code under test looks cannot see a repair raised under
    a key that tuple forgot.
    """
    return {key for key in (_UNCERTAIN, _UNLISTED) if _issue(coord, key) is not None}


# ---------------------------------------------------------------------------
# Which tiers prompt
# ---------------------------------------------------------------------------


def test_every_key_the_tier_table_can_return_is_reconciled() -> None:
    """Ties the two sources together.

    `_MODEL_SUPPORT_REPAIR_KEYS` is written out by hand so a key can be cleared
    after it stops applying — which means it can silently fall behind
    `repair_key_for_tier`. A key that table returns but this tuple omits would
    be raised and then never cleared again, and no other test would notice.
    """
    keys = {repair_key_for_tier(tier) for tier in [*SupportTier, None]}

    assert keys - {None} <= set(_MODEL_SUPPORT_REPAIR_KEYS)
    # And the other direction: a stale key nothing can raise is dead weight.
    assert set(_MODEL_SUPPORT_REPAIR_KEYS) <= keys - {None}


async def test_uncertain_model_prompts_for_a_report(hass: HomeAssistant) -> None:
    """UNCERTAIN is the tier that needs a human to say whether it works."""
    coord = _coord(hass, _device(SupportTier.UNCERTAIN))

    coord._apply_model_support_repair()

    assert _raised(coord) == {_UNCERTAIN}


async def test_unlisted_model_prompts_for_its_product_id(hass: HomeAssistant) -> None:
    """A model absent from the table needs a different thing: the ID itself, so
    it can be added at all. Hence its own key rather than reusing UNCERTAIN."""
    coord = _coord(hass, _device(None, model="9999999999999999999", pid="9999999999999999999"))

    coord._apply_model_support_repair()

    assert _raised(coord) == {_UNLISTED}


@pytest.mark.parametrize(
    "tier",
    [SupportTier.MAINTAINER_VERIFIED, SupportTier.COMMUNITY_VERIFIED, SupportTier.EXPECTED],
)
async def test_a_supported_tier_prompts_for_nothing(hass: HomeAssistant, tier: SupportTier) -> None:
    """The load-bearing negative. EXPECTED covers most models in the table, so a
    prompt here would be the common case and would train users to dismiss."""
    coord = _coord(hass, _device(tier))

    coord._apply_model_support_repair()

    assert _raised(coord) == set()


# ---------------------------------------------------------------------------
# Contents of the prompt
# ---------------------------------------------------------------------------


async def test_the_prompt_names_the_model_and_its_product_id(hass: HomeAssistant) -> None:
    """Both placeholders are filled from the device, not the translation. The
    product ID is the payload — a report without it cannot be acted on."""
    coord = _coord(hass, _device(SupportTier.UNCERTAIN))

    coord._apply_model_support_repair()

    issue = _issue(coord, _UNCERTAIN)
    assert issue is not None
    assert issue.translation_placeholders == {
        "model": "RVF 7",
        "product_id": "1950097634462887936",
    }
    assert issue.translation_key == _UNCERTAIN
    # WARNING because HA has nothing gentler; the description carries the tone.
    assert issue.severity is IssueSeverity.WARNING
    assert issue.is_fixable is False


async def test_setup_logs_loudly_only_when_it_also_prompts(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The log line and the prompt say the same thing, so they share a trigger.
    A warning on a model we are not warning the user about would be a log the
    maintainer learns to ignore."""
    quiet = _coord(hass, _device(SupportTier.EXPECTED))
    loud = _coord(hass, _device(SupportTier.UNCERTAIN))

    with caplog.at_level(logging.DEBUG, logger="custom_components.karcher_home_robots"):
        quiet._apply_model_support_repair()
        loud._apply_model_support_repair()

    levels = [r.levelno for r in caplog.records if r.getMessage().startswith("Model support:")]
    assert levels == [logging.DEBUG, logging.WARNING]


# ---------------------------------------------------------------------------
# Reconciliation across restarts
# ---------------------------------------------------------------------------


async def test_promoting_a_model_clears_its_old_prompt(hass: HomeAssistant) -> None:
    """The reason both keys are reconciled every setup rather than only the one
    that applies: an update that verifies a model must clear the stale issue by
    itself, not leave the user to dismiss it."""
    entry = make_entry()
    entry.add_to_hass(hass)
    coord = _coord(hass, _device(SupportTier.UNCERTAIN), entry)
    coord._apply_model_support_repair()
    assert _raised(coord) == {_UNCERTAIN}

    # Same config entry, same robot, new session: only the tier changed.
    promoted = _coord(hass, _device(SupportTier.COMMUNITY_VERIFIED), entry)
    promoted._apply_model_support_repair()

    assert _raised(promoted) == set()


async def test_adding_an_unlisted_model_to_the_table_clears_its_prompt(
    hass: HomeAssistant,
) -> None:
    """Same reconciliation, crossing between the two keys: a robot that was
    unlisted and is now EXPECTED must not keep the unlisted prompt."""
    entry = make_entry()
    entry.add_to_hass(hass)
    unlisted = _device(None, model="9999999999999999999", pid="9999999999999999999")
    coord = _coord(hass, unlisted, entry)
    coord._apply_model_support_repair()
    assert _raised(coord) == {_UNLISTED}

    listed = _coord(hass, replace(unlisted, support_tier=SupportTier.EXPECTED), entry)
    listed._apply_model_support_repair()

    assert _raised(listed) == set()


async def test_a_model_that_moves_between_prompts_shows_only_the_new_one(
    hass: HomeAssistant,
) -> None:
    """Removing a product ID from the table demotes UNCERTAIN → unlisted. Only
    one prompt may stand at a time; two would read as two separate problems."""
    entry = make_entry()
    entry.add_to_hass(hass)
    coord = _coord(hass, _device(SupportTier.UNCERTAIN), entry)
    coord._apply_model_support_repair()

    demoted = _coord(hass, _device(None), entry)
    demoted._apply_model_support_repair()

    assert _raised(demoted) == {_UNLISTED}


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


async def test_setup_raises_the_prompt_without_being_asked(hass: HomeAssistant) -> None:
    """Testing the function is not testing the wiring: async_setup has to call
    it, or none of the above ever reaches a user."""
    entry = make_entry()
    entry.add_to_hass(hass)
    adapter = AsyncMock()
    # Abort setup at the first await after the repair reconciliation, so this
    # asserts the call order rather than exercising the rest of setup.
    adapter.subscribe.side_effect = RuntimeError("stop here")
    coord = KarcherCoordinator(hass, adapter, _device(SupportTier.UNCERTAIN), config_entry=entry)

    with pytest.raises(RuntimeError, match="stop here"):
        await coord.async_setup()

    assert _raised(coord) == {_UNCERTAIN}


# ---------------------------------------------------------------------------
# Novel-value wiring
#
# NovelValueTracker's own rules are unit-tested. What can only be checked here
# is that both telemetry paths actually reach it: a value seen on one path only
# is exactly the case a hand-written call site forgets.
# ---------------------------------------------------------------------------

_NOVEL_WORK_MODE = 9001
_NOVEL_ZONE_TYPE = 9003


async def test_a_pushed_value_reaches_the_tracker(hass: HomeAssistant) -> None:
    coord = _coord(hass, _device(SupportTier.UNCERTAIN))

    coord._handle_push(make_props(work_mode=_NOVEL_WORK_MODE))
    await hass.async_block_till_done()

    assert coord.novel_values == {"work_mode": [_NOVEL_WORK_MODE]}


async def test_a_polled_value_reaches_the_tracker(hass: HomeAssistant) -> None:
    """The poll path is the one that matters for a robot controlled from the
    vendor app: MQTT is QoS 0, so a push can simply be lost."""
    entry = make_entry()
    entry.add_to_hass(hass)
    adapter = AsyncMock()
    adapter.fetch_properties.return_value = make_props(fault=_NOVEL_WORK_MODE)
    adapter.get_map_snapshot.return_value = None
    coord = KarcherCoordinator(hass, adapter, _device(SupportTier.UNCERTAIN), config_entry=entry)

    await coord._async_update_data()

    assert coord.novel_values == {"fault": [_NOVEL_WORK_MODE]}


async def test_a_known_value_leaves_the_record_empty(hass: HomeAssistant) -> None:
    """Guards the two tests above from passing on a tracker that records
    everything it is handed."""
    coord = _coord(hass, _device(SupportTier.UNCERTAIN))

    coord._handle_push(make_props(work_mode=0, fault=0))
    await hass.async_block_till_done()

    assert coord.novel_values == {}


async def test_an_unrecognised_zone_type_on_the_map_reaches_the_tracker(
    hass: HomeAssistant,
) -> None:
    """Restricted zones arrive on the map path, not the telemetry path, so they
    need their own call site — and a model that draws a zone type our renderer
    ignores is precisely the divergence this records."""
    entry = make_entry()
    entry.add_to_hass(hass)
    grid = MapGrid(width=8, height=8, data=b"\x00" * 16, resolution=0.05, min_x=0.0, min_y=0.0)
    adapter = AsyncMock()
    adapter.get_map_snapshot.return_value = MapSnapshot(
        grid=grid,
        robot=None,
        charger=None,
        zones=[
            RestrictedZone(zone_id=1, type_id=1, points=[(0.0, 0.0)]),
            RestrictedZone(zone_id=2, type_id=_NOVEL_ZONE_TYPE, points=[(0.0, 0.0)]),
        ],
    )
    coord = KarcherCoordinator(hass, adapter, _device(SupportTier.UNCERTAIN), config_entry=entry)

    await coord._refresh_map()

    assert coord.novel_values == {"zone_type": [_NOVEL_ZONE_TYPE]}
