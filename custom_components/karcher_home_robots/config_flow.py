"""Config flow for Kärcher Home Robots."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from karcher.exception import KarcherHomeException, KarcherHomeInvalidAuth

from .api import KarcherApi
from .hamh import configure_hamh_bridge
from .const import (
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    CONF_DEVICE_NICKNAME,
    CONF_DEVICE_SN,
    CONF_EMAIL,
    CONF_HAMH_PASSWORD,
    CONF_HAMH_URL,
    CONF_PASSWORD,
    DOMAIN,
    REGIONS,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_COUNTRY, default="EU"): vol.In(REGIONS),
    }
)

STEP_CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class KarcherOptionsFlow(config_entries.OptionsFlow):
    """Handle Kärcher integration options (HAMH URL)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_HAMH_URL,
                    default=self.config_entry.options.get(CONF_HAMH_URL, ""),
                ): str,
                vol.Optional(
                    CONF_HAMH_PASSWORD,
                    default=self.config_entry.options.get(CONF_HAMH_PASSWORD, ""),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class KarcherConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kärcher Home Robots."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> KarcherOptionsFlow:
        return KarcherOptionsFlow()

    def __init__(self) -> None:
        self._country: str | None = None
        self._email: str | None = None
        self._password: str | None = None
        self._api: KarcherApi | None = None
        self._devices: list = []
        self._pending_dev = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Pick region."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_SCHEMA
            )

        self._country = user_input[CONF_COUNTRY]
        return await self.async_step_credentials()

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Email + password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]

            try:
                api = KarcherApi(self._country)
                await api.authenticate(email, password)
                self._api = api
                self._email = email
                self._password = password
                self._devices = await api.get_devices()
            except KarcherHomeInvalidAuth:
                errors["base"] = "invalid_auth"
            except KarcherHomeException as err:
                _LOGGER.exception("Unexpected Kärcher error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during authentication")
                errors["base"] = "unknown"
            else:
                if not self._devices:
                    errors["base"] = "no_devices"
                elif len(self._devices) == 1:
                    self._pending_dev = self._devices[0]
                    return await self.async_step_hamh()
                else:
                    return await self.async_step_device()

        return self.async_show_form(
            step_id="credentials",
            data_schema=STEP_CREDENTIALS_SCHEMA,
            errors=errors,
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 3: Pick device (shown only if multiple devices exist)."""
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            dev = next((d for d in self._devices if d.device_id == device_id), None)
            if dev is not None:
                self._pending_dev = dev
                return await self.async_step_hamh()

        device_choices = {
            d.device_id: f"{d.nickname} ({d.sn})" for d in self._devices
        }
        schema = vol.Schema(
            {vol.Required(CONF_DEVICE_ID): vol.In(device_choices)}
        )
        return self.async_show_form(step_id="device", data_schema=schema)

    async def async_step_hamh(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Optional step: enter HAMH URL for Apple Home via Matter."""
        errors: dict[str, str] = {}

        hamh_error: str | None = None

        if user_input is not None:
            hamh_url = user_input.get(CONF_HAMH_URL, "").strip()
            hamh_password = user_input.get(CONF_HAMH_PASSWORD, "").strip() or None

            if hamh_url:
                try:
                    await configure_hamh_bridge(
                        hamh_url, hamh_password, self._pending_dev.nickname
                    )
                except Exception as err:
                    hamh_error = f"{type(err).__name__}: {err}"
                    _LOGGER.error("HAMH auto-configuration failed: %s", hamh_error, exc_info=True)
                    errors["base"] = "hamh_failed"

            if not errors:
                return await self._create_entry(
                    self._pending_dev,
                    options={
                        CONF_HAMH_URL: hamh_url,
                        CONF_HAMH_PASSWORD: hamh_password or "",
                    },
                )

        schema = vol.Schema(
            {
                vol.Optional(CONF_HAMH_URL, default=""): str,
                vol.Optional(CONF_HAMH_PASSWORD, default=""): str,
            }
        )
        description_placeholders = {"error": hamh_error} if hamh_error else None
        return self.async_show_form(
            step_id="hamh",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle re-authentication when credentials are rejected."""
        self._country = entry_data.get(CONF_COUNTRY)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Re-authentication form: collect new email + password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]

            try:
                api = KarcherApi(self._country)
                await api.authenticate(email, password)
                await api.close()
            except KarcherHomeInvalidAuth:
                errors["base"] = "invalid_auth"
            except KarcherHomeException as err:
                _LOGGER.exception("Re-auth Kärcher error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during re-authentication")
                errors["base"] = "unknown"
            else:
                entry = self.hass.config_entries.async_get_entry(
                    self.context["entry_id"]
                )
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_EMAIL: email, CONF_PASSWORD: password},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_CREDENTIALS_SCHEMA,
            errors=errors,
        )

    async def _create_entry(
        self, dev, options: dict | None = None
    ) -> FlowResult:
        await self.async_set_unique_id(dev.device_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=dev.nickname,
            data={
                CONF_COUNTRY: self._country,
                CONF_EMAIL: self._email,
                CONF_PASSWORD: self._password,
                CONF_DEVICE_ID: dev.device_id,
                CONF_DEVICE_SN: dev.sn,
                CONF_DEVICE_NICKNAME: dev.nickname,
            },
            options=options or {},
        )
