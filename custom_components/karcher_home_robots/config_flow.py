# SPDX-License-Identifier: MIT
"""Config flow — region → credentials → (optional) device picker → reauth.

Steps (FR-A-1..FR-A-11):
  1. user:    country code (drives region-endpoint selection)
  2. credentials: email + password
  3. device (optional): pick one when > 1 device on the account
  Reauth: password only; country + device_id are taken from the entry.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
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

from .adapter import AdapterConfig, Device, KarcherAdapter
from .const import DOMAIN
from .exceptions import AuthError, ClientError

_LOGGER = logging.getLogger(__name__)

CONF_COUNTRY = "country"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"  # noqa: S105
CONF_DEVICE_ID = "device_id"

_DEFAULT_COUNTRY = "GB"


class KarcherConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Kärcher Home Robots.

    VERSION = 2 matches the migration contract (spec/03 §10, FR-MG-2).
    """

    VERSION = 2

    def __init__(self) -> None:
        self._country: str = _DEFAULT_COUNTRY
        self._email: str = ""
        self._password: str = ""
        self._devices: list[Device] = []

    # ------------------------------------------------------------------
    # Step 1: country
    # ------------------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1 — country selection.

        Covers: FR-A-1
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            self._country = user_input[CONF_COUNTRY].strip().upper()
            if not self._country:
                errors[CONF_COUNTRY] = "invalid_country"
            else:
                return await self.async_step_credentials()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_COUNTRY,
                        default=getattr(self, "_country", _DEFAULT_COUNTRY),
                    ): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="country")
                    ),
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2: credentials
    # ------------------------------------------------------------------

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2 — email + password.

        Covers: FR-A-2, FR-A-6, FR-A-8, FR-A-9
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            self._password = user_input[CONF_PASSWORD]
            error_key, devices = await _try_authenticate(
                self.hass, self._country, self._email, self._password
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

    # ------------------------------------------------------------------
    # Step 3: device picker (multi-device accounts only)
    # ------------------------------------------------------------------

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 3 — pick one device when the account has > 1.

        Covers: FR-A-4
        """
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

    # ------------------------------------------------------------------
    # Reauth flow (FR-A-7, FR-A-11)
    # ------------------------------------------------------------------

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Reauth triggered by ConfigEntryAuthFailed.

        Covers: FR-A-7, FR-A-11
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the new password; country + device_id come from the entry.

        Covers: FR-A-11
        """
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            country = entry.data[CONF_COUNTRY]
            email = entry.data[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            error_key, _ = await _try_authenticate(self.hass, country, email, password)
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _create_entry(self, device: Device) -> ConfigFlowResult:
        """Deduplicate and create the config entry.

        Covers: FR-A-5
        """
        await self.async_set_unique_id(device.device_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=device.nickname or device.sn,
            data={
                CONF_COUNTRY: self._country,
                CONF_EMAIL: self._email,
                CONF_PASSWORD: self._password,
                CONF_DEVICE_ID: device.device_id,
                "sn": device.sn,
                "product_id": device.product_id,
                "nickname": device.nickname,
            },
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


async def _try_authenticate(
    hass: HomeAssistant,
    country: str,
    email: str,
    password: str,
) -> tuple[str | None, list[Device]]:
    """Attempt authenticate + get_devices; return (error_key, devices).

    Returns (None, devices) on success, (error_key, []) on failure.
    Covers: FR-A-6
    """
    adapter = KarcherAdapter(hass, AdapterConfig(country=country))
    try:
        await adapter.async_setup()
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
