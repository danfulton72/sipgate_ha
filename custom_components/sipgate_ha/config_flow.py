"""Config flow for sipgate.io."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_TOKEN, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    SipgateApiError,
    SipgateAuthenticationError,
    SipgateClient,
    SipgateConnectionError,
)
from .const import (
    CONF_CONTACTS,
    CONF_INCLUDE_OUTGOING,
    CONF_PUBLIC_URL,
    CONF_SIGNIFICANT_DIGITS,
    CONF_TOKEN_ID,
    DEFAULT_INCLUDE_OUTGOING,
    DEFAULT_SIGNIFICANT_DIGITS,
    DOMAIN,
    NAME,
)
from .helpers import (
    InvalidPublicUrl,
    build_webhook_url,
    normalize_public_url,
    parse_contacts,
)

TOKEN_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)
URL_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.URL, autocomplete="url")
)
CONTACTS_SELECTOR = TextSelector(TextSelectorConfig(multiline=True))
DIGITS_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=7, max=15, step=1, mode=NumberSelectorMode.BOX)
)


async def _async_validate_credentials(
    hass: HomeAssistant, token_id: str, token: str
) -> dict[str, str]:
    """Validate sipgate credentials and return config-flow errors."""
    client = SipgateClient(async_get_clientsession(hass), token_id, token)
    try:
        await client.async_validate_credentials()
    except SipgateAuthenticationError:
        return {"base": "invalid_auth"}
    except SipgateConnectionError:
        return {"base": "cannot_connect"}
    except SipgateApiError:
        return {"base": "unknown"}
    return {}


class SipgateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for sipgate.io."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._pending_data: dict[str, Any] | None = None
        self._webhook_url: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SipgateOptionsFlow:
        """Return the options flow."""
        return SipgateOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up sipgate.io from the UI."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                public_url = normalize_public_url(user_input[CONF_PUBLIC_URL])
            except InvalidPublicUrl:
                errors[CONF_PUBLIC_URL] = "invalid_url"
            else:
                errors = await _async_validate_credentials(
                    self.hass,
                    user_input[CONF_TOKEN_ID].strip(),
                    user_input[CONF_TOKEN],
                )
                if not errors:
                    webhook_id = webhook.async_generate_id()
                    self._pending_data = {
                        CONF_TOKEN_ID: user_input[CONF_TOKEN_ID].strip(),
                        CONF_TOKEN: user_input[CONF_TOKEN],
                        CONF_PUBLIC_URL: public_url,
                        CONF_WEBHOOK_ID: webhook_id,
                    }
                    self._webhook_url = build_webhook_url(public_url, webhook_id)
                    return await self.async_step_webhook()

        schema = vol.Schema(
            {
                vol.Required(CONF_TOKEN_ID): str,
                vol.Required(CONF_TOKEN): TOKEN_SELECTOR,
                vol.Required(CONF_PUBLIC_URL, default="https://"): URL_SELECTOR,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the webhook URL before creating the entry."""
        if self._pending_data is None or self._webhook_url is None:
            return self.async_abort(reason="unknown")

        if user_input is not None:
            return self.async_create_entry(title=NAME, data=self._pending_data)

        return self.async_show_form(
            step_id="webhook",
            data_schema=vol.Schema({}),
            description_placeholders={"webhook_url": self._webhook_url},
            last_step=True,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after an authentication failure."""
        del entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect replacement PAT credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await _async_validate_credentials(
                self.hass, user_input[CONF_TOKEN_ID].strip(), user_input[CONF_TOKEN]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_TOKEN_ID: user_input[CONF_TOKEN_ID].strip(),
                        CONF_TOKEN: user_input[CONF_TOKEN],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_TOKEN_ID, default=entry.data[CONF_TOKEN_ID]): str,
                vol.Required(CONF_TOKEN): TOKEN_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure credentials or the externally reachable HA URL."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                public_url = normalize_public_url(user_input[CONF_PUBLIC_URL])
            except InvalidPublicUrl:
                errors[CONF_PUBLIC_URL] = "invalid_url"
            else:
                errors = await _async_validate_credentials(
                    self.hass,
                    user_input[CONF_TOKEN_ID].strip(),
                    user_input[CONF_TOKEN],
                )
                if not errors:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_TOKEN_ID: user_input[CONF_TOKEN_ID].strip(),
                            CONF_TOKEN: user_input[CONF_TOKEN],
                            CONF_PUBLIC_URL: public_url,
                        },
                    )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TOKEN_ID, default=entry.data[CONF_TOKEN_ID]
                ): str,
                vol.Required(CONF_TOKEN): TOKEN_SELECTOR,
                vol.Required(
                    CONF_PUBLIC_URL, default=entry.data[CONF_PUBLIC_URL]
                ): URL_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )


class SipgateOptionsFlow(OptionsFlow):
    """Configure non-connection sipgate.io options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parse_contacts(
                    user_input[CONF_CONTACTS], int(user_input[CONF_SIGNIFICANT_DIGITS])
                )
            except ValueError:
                errors[CONF_CONTACTS] = "invalid_contacts"
            else:
                return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_INCLUDE_OUTGOING,
                    default=options.get(
                        CONF_INCLUDE_OUTGOING, DEFAULT_INCLUDE_OUTGOING
                    ),
                ): bool,
                vol.Required(
                    CONF_SIGNIFICANT_DIGITS,
                    default=options.get(
                        CONF_SIGNIFICANT_DIGITS, DEFAULT_SIGNIFICANT_DIGITS
                    ),
                ): DIGITS_SELECTOR,
                vol.Optional(
                    CONF_CONTACTS, default=options.get(CONF_CONTACTS, "")
                ): CONTACTS_SELECTOR,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
