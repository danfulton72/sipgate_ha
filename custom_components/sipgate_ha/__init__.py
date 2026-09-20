"""Native Home Assistant integration for sipgate.io call webhooks."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
import logging

import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import (
    SipgateApiError,
    SipgateAuthenticationError,
    SipgateClient,
    SipgateConnectionError,
)
from .const import (
    ATTR_CALL_ID,
    CONF_PUBLIC_URL,
    CONF_TOKEN_ID,
    DOMAIN,
    NAME,
    SERVICE_HANG_UP,
)
from .helpers import build_webhook_url
from .webhook import async_handle_webhook

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SipgateRuntimeData:
    """Runtime data for the configured sipgate account."""

    client: SipgateClient
    webhook_url: str


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the sipgate.io integration."""
    del config

    async def async_hang_up(call: ServiceCall) -> None:
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError("sipgate.io is not configured or loaded")

        runtime = entries[0].runtime_data
        if not isinstance(runtime, SipgateRuntimeData):
            raise ServiceValidationError("sipgate.io is not ready")

        try:
            await runtime.client.async_hang_up(call.data[ATTR_CALL_ID])
        except SipgateAuthenticationError as err:
            raise HomeAssistantError(
                "sipgate rejected the configured credentials"
            ) from err
        except SipgateConnectionError as err:
            raise HomeAssistantError("Could not connect to sipgate") from err
        except SipgateApiError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_HANG_UP,
        async_hang_up,
        schema=vol.Schema({vol.Required(ATTR_CALL_ID): cv.string}),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up sipgate.io from a config entry."""
    client = SipgateClient(
        async_get_clientsession(hass),
        entry.data[CONF_TOKEN_ID],
        entry.data[CONF_TOKEN],
    )

    try:
        await client.async_validate_credentials()
    except SipgateAuthenticationError as err:
        raise ConfigEntryAuthFailed("Invalid sipgate credentials") from err
    except SipgateConnectionError as err:
        raise ConfigEntryNotReady("Could not connect to sipgate") from err
    except SipgateApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    webhook_id = entry.data[CONF_WEBHOOK_ID]
    webhook_url = build_webhook_url(entry.data[CONF_PUBLIC_URL], webhook_id)
    entry.runtime_data = SipgateRuntimeData(client=client, webhook_url=webhook_url)

    webhook.async_register(
        hass,
        DOMAIN,
        NAME,
        webhook_id,
        partial(async_handle_webhook, entry=entry, webhook_url=webhook_url),
        allowed_methods=("POST",),
    )
    entry.async_on_unload(partial(webhook.async_unregister, hass, webhook_id))
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options or connection data change."""
    await hass.config_entries.async_reload(entry.entry_id)
