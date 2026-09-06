# SPDX-License-Identifier: MIT
"""Product-ID → model profile table, and the support tier each model carries.

Adding a robot model is a one-row edit to `PROFILES` below, plus a
`CHANGELOG.md` line. The README table is generated from this file — run
`python tests/tools/check_docs.py --fix-model-table` and commit the result.
See `CONTRIBUTING.md` for the tier adjudication rule.

**Every model gets the full entity set.** A tier is a statement about how much
evidence we have, not a capability gate: it drives the device-registry name, a
diagnostics field, one setup log line, and a repair prompt — nothing else. Do
not add a `supported_platforms` column, however natural it looks beside
`evidence`; withholding entities from unverified models is a design this
project tried and rejected, because it would have withheld from the RVM 4
exactly the entities that turned out to work.

**Lookup is by product ID, never by enum member name.** The cloud's product ID
is the stable identity; enum member names are the pinned library's, and it
mislabels one (`RCF5` for the ID Kärcher itself calls RCF3 — `doc/PROTOCOL.md`
§16.7). Keying on the ID means a patched fork that renames a member changes
nothing here.

Deliberately dependency-free: stdlib only, no `homeassistant`, no `karcher`,
and **no relative imports**. `tests/tools/check_docs.py` loads this file by
path with no venv and no package import, so any import of a sibling module
would drag in `__init__.py` and, with it, Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SupportTier(StrEnum):
    """How much evidence we have that a model works. Not a capability gate."""

    MAINTAINER_VERIFIED = "maintainer_verified"
    COMMUNITY_VERIFIED = "community_verified"
    EXPECTED = "expected"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """One robot model, keyed by the cloud's product ID."""

    product_id: str
    """Decimal string, exactly as the cloud reports it. The stable identity."""

    member_name: str
    """Enum member name used when the pinned library does not know this ID.

    Its own field rather than a mangling of `display_name`, because enum member
    names must be valid identifiers and "RVM 4 Comfort" is not. Deriving one by
    stripping spaces produces collisions no reviewer can see, and the failure
    mode is an ImportError inside a user's Home Assistant that ruff cannot catch.
    """

    display_name: str
    """Kärcher's own spelling, for the Home Assistant device registry."""

    tier: SupportTier

    evidence: str
    """One line, rendered into the README table. Say what backs the tier."""


# The property-schema template every EXPECTED row below inherits from. RVM 4
# sits on it and is community-verified, which is the whole basis for expecting
# its co-tenants to work (doc/PROTOCOL.md §16.5).
COMMON_TEMPLATE = "1483728197182287872"

# RCV 5's own template. Worth naming explicitly because it is a SINGLETON:
# Kärcher's backend groups the RCV 5 with nothing, not even the RCV 3. So no
# model inherits EXPECTED from the maintainer-verified row — the EXPECTED rows
# below all inherit from the RVM 4 instead. This is the evidence that overturned
# an earlier design in which unverified models were shipped without entities.
RCV5_TEMPLATE = "1534049550200303616"

# RVF 7's template. Camera and voice over Agora; least likely to transfer.
RVF7_TEMPLATE = "1688471264069652480"


PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile(
        product_id="1540149850806333440",
        member_name="RCV5",
        display_name="RCV 5",
        tier=SupportTier.MAINTAINER_VERIFIED,
        evidence="Maintainer's own hardware; the HIL suite runs against it.",
    ),
    ModelProfile(
        product_id="1946123509838999552",
        member_name="RVM4",
        display_name="RVM 4 Comfort",
        tier=SupportTier.COMMUNITY_VERIFIED,
        evidence=(
            "Community report of working control on this exact product ID. "
            "Pairs through the Kärcher Indoor Robots app, same cloud endpoint."
        ),
    ),
    ModelProfile(
        product_id="1528986273083777024",
        member_name="RCV3",
        display_name="RCV 3",
        tier=SupportTier.EXPECTED,
        evidence=f"Shares property-schema template {COMMON_TEMPLATE} with the RVM 4.",
    ),
    ModelProfile(
        product_id="1599715149861306368",
        member_name="RCF3",
        display_name="RCF 3",
        tier=SupportTier.EXPECTED,
        evidence=f"Shares property-schema template {COMMON_TEMPLATE} with the RVM 4.",
    ),
    ModelProfile(
        product_id="1703609713493610496",
        member_name="RCV2",
        display_name="RCV 2",
        tier=SupportTier.EXPECTED,
        evidence=f"Shares property-schema template {COMMON_TEMPLATE} with the RVM 4.",
    ),
    ModelProfile(
        product_id="1946027907671224320",
        member_name="RVC3",
        display_name="RVC 3",
        tier=SupportTier.EXPECTED,
        evidence=f"Shares property-schema template {COMMON_TEMPLATE} with the RVM 4.",
    ),
    ModelProfile(
        product_id="1946028477060575232",
        member_name="RVC3_COMFORT",
        display_name="RVC 3 Comfort",
        tier=SupportTier.EXPECTED,
        evidence=f"Shares property-schema template {COMMON_TEMPLATE} with the RVM 4.",
    ),
    ModelProfile(
        product_id="1950097634462887936",
        member_name="RVF7",
        display_name="RVF 7",
        tier=SupportTier.UNCERTAIN,
        evidence=(
            f"Own property-schema template {RVF7_TEMPLATE}; adds camera and voice over Agora."
        ),
    ),
    ModelProfile(
        product_id="1950097614355394560",
        member_name="RVF7_COMFORT",
        display_name="RVF 7 Comfort",
        tier=SupportTier.UNCERTAIN,
        evidence=(
            f"Own property-schema template {RVF7_TEMPLATE}; adds camera and voice over Agora."
        ),
    ),
    ModelProfile(
        product_id="1670775876502392832",
        member_name="RCV3_JA",
        display_name="RCV 3 (JP)",
        tier=SupportTier.UNCERTAIN,
        evidence="Known from the vendor app only; absent from the live catalog, so no template.",
    ),
    ModelProfile(
        product_id="1670774796888543232",
        member_name="RCV5_JA",
        display_name="RCV 5 (JP)",
        tier=SupportTier.UNCERTAIN,
        evidence="Known from the vendor app only; absent from the live catalog, so no template.",
    ),
)

_BY_PRODUCT_ID: dict[str, ModelProfile] = {p.product_id: p for p in PROFILES}


def profile_for(product_id: str) -> ModelProfile | None:
    """The profile for a product ID, or None if the table does not list it."""
    return _BY_PRODUCT_ID.get(product_id)


def display_name(product_id: str) -> str:
    """Human-readable model for the device registry.

    Falls back to the raw product ID so an unlisted robot still registers
    honestly, rather than under some other model's name.
    """
    profile = _BY_PRODUCT_ID.get(product_id)
    return profile.display_name if profile else product_id


def tier_for(product_id: str) -> SupportTier | None:
    """Support tier, or None when the table does not list this product ID.

    Unlisted is a fifth state, deliberately not a fifth enum member: the ask is
    different. An UNCERTAIN model needs someone to say whether it works; an
    unlisted one needs its ID reported so it can be added at all.
    """
    profile = _BY_PRODUCT_ID.get(product_id)
    return profile.tier if profile else None


def repair_key_for_tier(tier: SupportTier | None) -> str | None:
    """Repair issue to raise for a tier, or None to stay silent.

    Silence on EXPECTED and both verified tiers is the load-bearing half.
    Firing on EXPECTED would prompt most new users and train them to dismiss
    repairs; firing on a verified tier is noise when a peer already confirmed
    the model works.

    Exhaustive over SupportTier on purpose, and there is deliberately no
    `case _`: adding a tier without deciding its repair behaviour then leaves an
    implicit fall-through, which `mypy --strict` (a blocking CI gate) reports as
    "Missing return statement" on this function. A catch-all would silence that
    and let the new tier default to silence unnoticed.
    """
    match tier:
        case None:
            return "model_support_unlisted"
        case SupportTier.UNCERTAIN:
            return "model_support_uncertain"
        case (
            SupportTier.MAINTAINER_VERIFIED | SupportTier.COMMUNITY_VERIFIED | SupportTier.EXPECTED
        ):
            return None


_TIER_LABELS: dict[SupportTier, str] = {
    SupportTier.MAINTAINER_VERIFIED: "✅ Maintainer-verified",
    SupportTier.COMMUNITY_VERIFIED: "✅ Community-verified",
    SupportTier.EXPECTED: "🟡 Expected to work",
    SupportTier.UNCERTAIN: "⚠️ Uncertain",
}

README_BEGIN = "<!-- BEGIN GENERATED: supported-models -->"
README_END = "<!-- END GENERATED: supported-models -->"


def render_readme_block() -> str:
    """The README's supported-models region, generated from PROFILES.

    Lives here rather than in the docs checker so the renderer ships with the
    table it renders; `tests/tools/check_docs.py` imports it by path.
    """
    lines = [
        README_BEGIN,
        "",
        "| Model | Product ID | Support | Why |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| **{p.display_name}** | `{p.product_id}` | {_TIER_LABELS[p.tier]} | {p.evidence} |"
        for p in PROFILES
    ]
    lines += [
        "",
        "**Every model above gets the full entity set.** The support level says how much "
        "evidence we have that it works — it does not withhold features.",
        "",
        f"- {_TIER_LABELS[SupportTier.MAINTAINER_VERIFIED]} — the maintainer owns this robot "
        "and the hardware test suite runs against it.",
        f"- {_TIER_LABELS[SupportTier.COMMUNITY_VERIFIED]} — a user reported working control "
        "on this exact product ID.",
        f"- {_TIER_LABELS[SupportTier.EXPECTED]} — Kärcher's backend puts this model on the "
        "same property schema as a verified one, so its properties should behave the same. "
        "Untested.",
        f"- {_TIER_LABELS[SupportTier.UNCERTAIN]} — no shared-schema evidence either way. "
        "Setup works and every entity appears; individual values may be wrong.",
        "",
        "**A robot that is not listed at all still sets up** and gets the full entity set — "
        "it registers under its raw product ID. Please open an issue with that ID so it can "
        "be added.",
        "",
        README_END,
    ]
    return "\n".join(lines)
