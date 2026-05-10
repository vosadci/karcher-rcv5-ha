# SPDX-License-Identifier: MIT
"""Integration tests for the config flow."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from custom_components.karcher_home_robots.adapter import Device
from custom_components.karcher_home_robots.config_flow import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REGION,
    _try_authenticate,
)
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.exceptions import AuthError, ClientError
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import PROPS_IDLE, TEST_DEVICE, FakeAdapter, patch_adapter

_DEVICE_A = Device(
    device_id="dev-a",
    sn="SN-A",
    product_id="1540149850806333440",
    nickname="Robot A",
    mac="AA:BB:CC:DD:EE:FF",
    product_mode_code="CRL350",
)
_DEVICE_B = Device(
    device_id="dev-b",
    sn="SN-B",
    product_id="1540149850806333440",
    nickname="Robot B",
    mac="AA:BB:CC:DD:EE:F0",
    product_mode_code="CRL350",
)


def _patch_try_authenticate(
    error_key: str | None = None,
    devices: list[Device] | None = None,
) -> Any:
    """Patch _try_authenticate to return canned (error_key, devices)."""
    result_devices = devices if devices is not None else [TEST_DEVICE]
    return patch(
        "custom_components.karcher_home_robots.config_flow._try_authenticate",
        return_value=(error_key, [] if error_key else result_devices),
    )


def _patch_validate_credentials(error_key: str | None = None) -> Any:
    """Patch _validate_credentials to return a canned error key (or None)."""
    return patch(
        "custom_components.karcher_home_robots.config_flow._validate_credentials",
        return_value=error_key,
    )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_flow_single_device_completes(hass: HomeAssistant) -> None:
    """One-device account: region → credentials → entry created (no device step)."""
    fake = FakeAdapter(props=PROPS_IDLE)
    with _patch_try_authenticate(devices=[TEST_DEVICE]), patch_adapter(fake):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REGION: "eu"}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "credentials"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "test@example.com", CONF_PASSWORD: "secret"},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_REGION] == "eu"
    assert result["data"][CONF_EMAIL] == "test@example.com"
    assert result["data"][CONF_DEVICE_ID] == TEST_DEVICE.device_id


async def test_flow_multi_device_shows_picker(hass: HomeAssistant) -> None:
    """Two-device account shows device picker step then creates entry on selection."""
    fake = FakeAdapter(props=PROPS_IDLE, devices=[_DEVICE_A])
    with _patch_try_authenticate(devices=[_DEVICE_A, _DEVICE_B]), patch_adapter(fake):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REGION: "us"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "pass"},
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "device"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DEVICE_ID: _DEVICE_B.device_id}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_ID] == _DEVICE_B.device_id


async def test_flow_deduplicates_unique_id(hass: HomeAssistant) -> None:
    """Second flow for the same device_id is aborted."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=TEST_DEVICE.device_id,
        data={},
        version=3,
    )
    existing.add_to_hass(hass)

    fake = FakeAdapter()
    with _patch_try_authenticate(devices=[TEST_DEVICE]), patch_adapter(fake):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REGION: "eu"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "test@example.com", CONF_PASSWORD: "secret"},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


async def test_flow_invalid_auth_shows_error(hass: HomeAssistant) -> None:
    """Auth failure shows invalid_auth on the credentials form."""
    with _patch_try_authenticate(error_key="invalid_auth"):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REGION: "eu"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "bad@example.com", CONF_PASSWORD: "wrong"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "credentials"
    assert result["errors"]["base"] == "invalid_auth"


async def test_flow_cannot_connect_shows_error(hass: HomeAssistant) -> None:
    """Network failure shows cannot_connect on the credentials form."""
    with _patch_try_authenticate(error_key="cannot_connect"):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REGION: "eu"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "test@example.com", CONF_PASSWORD: "pass"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


async def test_flow_no_devices_shows_error(hass: HomeAssistant) -> None:
    """Empty device list shows no_devices on the credentials form."""
    with patch(
        "custom_components.karcher_home_robots.config_flow._try_authenticate",
        return_value=(None, []),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REGION: "eu"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "test@example.com", CONF_PASSWORD: "pass"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "no_devices"


# ---------------------------------------------------------------------------
# _try_authenticate unit paths (called directly to cover exception branches)
# ---------------------------------------------------------------------------


async def test_try_authenticate_auth_error(hass: HomeAssistant) -> None:
    """AuthError maps to invalid_auth."""
    adapter_mock = _FakeFlowAdapter(authenticate_raises=AuthError("bad"))
    with patch(
        "custom_components.karcher_home_robots.config_flow.KarcherAdapter",
        side_effect=lambda *a, **kw: adapter_mock,
    ):
        key, devices = await _try_authenticate(hass, "eu", "u@e.com", "pw")

    assert key == "invalid_auth"
    assert devices == []
    assert adapter_mock.closed


async def test_try_authenticate_client_error(hass: HomeAssistant) -> None:
    """ClientError maps to cannot_connect."""
    adapter_mock = _FakeFlowAdapter(authenticate_raises=ClientError("net"))
    with patch(
        "custom_components.karcher_home_robots.config_flow.KarcherAdapter",
        side_effect=lambda *a, **kw: adapter_mock,
    ):
        key, _devices = await _try_authenticate(hass, "eu", "u@e.com", "pw")

    assert key == "cannot_connect"
    assert adapter_mock.closed


async def test_try_authenticate_unexpected_error(hass: HomeAssistant) -> None:
    """An unexpected exception maps to unknown."""
    adapter_mock = _FakeFlowAdapter(authenticate_raises=RuntimeError("boom"))
    with patch(
        "custom_components.karcher_home_robots.config_flow.KarcherAdapter",
        side_effect=lambda *a, **kw: adapter_mock,
    ):
        key, _devices = await _try_authenticate(hass, "eu", "u@e.com", "pw")

    assert key == "unknown"
    assert adapter_mock.closed


async def test_try_authenticate_success(hass: HomeAssistant) -> None:
    """Successful auth returns (None, devices)."""
    adapter_mock = _FakeFlowAdapter(devices=[TEST_DEVICE])
    with patch(
        "custom_components.karcher_home_robots.config_flow.KarcherAdapter",
        side_effect=lambda *a, **kw: adapter_mock,
    ):
        key, devices = await _try_authenticate(hass, "eu", "u@e.com", "pw")

    assert key is None
    assert devices == [TEST_DEVICE]
    assert adapter_mock.closed


# ---------------------------------------------------------------------------
# Reauth flow
# ---------------------------------------------------------------------------


async def test_reauth_flow_updates_password(hass: HomeAssistant) -> None:
    """Reauth flow updates only the password and reloads the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REGION: "eu",
            CONF_EMAIL: "test@example.com",
            CONF_PASSWORD: "old-password",
            CONF_DEVICE_ID: TEST_DEVICE.device_id,
        },
        unique_id=TEST_DEVICE.device_id,
        version=3,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    fake = FakeAdapter(props=PROPS_IDLE)
    with (
        _patch_validate_credentials(),
        patch_adapter(fake),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new-password"}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"


async def test_reauth_flow_bad_password_shows_error(hass: HomeAssistant) -> None:
    """Wrong password during reauth shows invalid_auth."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REGION: "eu",
            CONF_EMAIL: "test@example.com",
            CONF_PASSWORD: "old-password",
            CONF_DEVICE_ID: TEST_DEVICE.device_id,
        },
        unique_id=TEST_DEVICE.device_id,
        version=3,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=entry.data,
    )

    with _patch_validate_credentials(error_key="invalid_auth"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "wrong"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"]["base"] == "invalid_auth"


# ---------------------------------------------------------------------------
# Helper: fake adapter for _try_authenticate tests
# ---------------------------------------------------------------------------


class _FakeFlowAdapter:
    def __init__(
        self,
        *,
        authenticate_raises: Exception | None = None,
        devices: list[Device] | None = None,
    ) -> None:
        self._authenticate_raises = authenticate_raises
        self._devices = devices or []
        self.closed = False

    async def async_setup(self) -> None:
        pass

    async def authenticate(self, email: str, password: str) -> None:
        if self._authenticate_raises:
            raise self._authenticate_raises

    async def get_devices(self) -> list[Device]:
        return self._devices

    async def close(self) -> None:
        self.closed = True
