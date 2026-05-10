# SPDX-License-Identifier: MIT
"""Config flow — region → credentials → (optional) device picker → reauth."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from ._account_registry import get_shared_adapter
from .adapter import AdapterConfig, Device, KarcherAdapter
from .const import DOMAIN
from .exceptions import AuthError, ClientError

_LOGGER = logging.getLogger(__name__)

CONF_REGION = "region"
CONF_DEVICE_ID = "device_id"

_REGION_OPTIONS: list[SelectOptionDict] = [
    SelectOptionDict(value="eu", label="Europe / Rest of World"),
    SelectOptionDict(value="us", label="United States / Americas"),
    SelectOptionDict(value="cn", label="China / Asia-Pacific"),
]
_DEFAULT_REGION = "eu"


class KarcherConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Kärcher Home Robots."""

    VERSION = 3

    def __init__(self) -> None:
        self._region: str = _DEFAULT_REGION
        self._email: str = ""
        self._password: str = ""
        self._devices: list[Device] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._region = user_input[CONF_REGION]
            return await self.async_step_credentials()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REGION, default=self._region): SelectSelector(
                        SelectSelectorConfig(
                            options=_REGION_OPTIONS,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            self._password = user_input[CONF_PASSWORD]
            error_key, devices = await _try_authenticate(
                self.hass, self._region, self._email, self._password
            )
            if error_key is not None:
                errors["base"] = error_key
            elif not devices:
                errors["base"] = "no_devices"
            elif len(devices) == 1:
                return await self._create_entry(devices[0])
            else:
                self._devices = devices
                return await self.async_step_device()

        return self.async_show_form(
            step_id="credentials",
            data_schema=_credentials_schema(self._email),
            errors=errors,
        )

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            device = next((d for d in self._devices if d.device_id == device_id), None)
            if device is None:
                return self.async_abort(reason="device_not_found")
            return await self._create_entry(device)

        options: list[SelectOptionDict] = [
            SelectOptionDict(value=d.device_id, label=d.nickname or d.sn) for d in self._devices
        ]
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            region = entry.data[CONF_REGION]
            email = entry.data[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            error_key = await _validate_credentials(self.hass, region, email, password)
            if error_key is not None:
                errors["base"] = error_key
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_PASSWORD: password},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_password_schema(),
            errors=errors,
            description_placeholders={"email": entry.data.get(CONF_EMAIL, "")},
        )

    async def _create_entry(self, device: Device) -> ConfigFlowResult:
        await self.async_set_unique_id(device.device_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=device.nickname or device.sn,
            data={
                CONF_REGION: self._region,
                CONF_EMAIL: self._email,
                CONF_PASSWORD: self._password,
                CONF_DEVICE_ID: device.device_id,
            },
        )


async def _try_authenticate(
    hass: HomeAssistant,
    region: str,
    email: str,
    password: str,
) -> tuple[str | None, list[Device]]:
    """Validate credentials and return (error_key, devices).

    If a shared adapter for *email* is already running, reuse it for the
    device list without firing a new login() — the credentials were already
    validated when the shared adapter was created.  Otherwise create a
    temporary adapter, validate, then close it.
    """
    shared = get_shared_adapter(hass, email)
    if shared is not None:
        return await _get_devices_from_shared(shared)

    adapter = KarcherAdapter(hass, AdapterConfig(region=region))
    await adapter.async_setup()
    return await _login_and_get_devices(adapter, email, password)


async def _get_devices_from_shared(
    adapter: KarcherAdapter,
) -> tuple[str | None, list[Device]]:
    try:
        devices = await adapter.get_devices()
        return None, devices
    except AuthError:
        return "invalid_auth", []
    except ClientError:
        return "cannot_connect", []
    except Exception:
        _LOGGER.exception("Unexpected error fetching devices via shared adapter")
        return "unknown", []


async def _login_and_get_devices(
    adapter: KarcherAdapter,
    email: str,
    password: str,
) -> tuple[str | None, list[Device]]:
    try:
        await adapter.authenticate(email, password)
        devices = await adapter.get_devices()
        return None, devices
    except AuthError:
        return "invalid_auth", []
    except ClientError:
        return "cannot_connect", []
    except Exception:
        _LOGGER.exception("Unexpected error during config flow auth")
        return "unknown", []
    finally:
        await adapter.close()


async def _validate_credentials(
    hass: HomeAssistant,
    region: str,
    email: str,
    password: str,
) -> str | None:
    """Check that *password* is accepted by the cloud; return an error key or None.

    Always uses a temporary adapter so the shared adapter's session is never
    disturbed.  Used by the reauth flow where we need to verify a new password
    without invalidating an already-running session for another robot on the
    same account.
    """
    adapter = KarcherAdapter(hass, AdapterConfig(region=region))
    await adapter.async_setup()
    error_key, _ = await _login_and_get_devices(adapter, email, password)
    return error_key


def _credentials_schema(email: str = "") -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_EMAIL, default=email): TextSelector(
                TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="email")
            ),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(
                    type=TextSelectorType.PASSWORD,
                    autocomplete="current-password",
                )
            ),
        }
    )


def _password_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(
                    type=TextSelectorType.PASSWORD,
                    autocomplete="current-password",
                )
            ),
        }
    )
