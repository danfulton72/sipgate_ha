"""Native Home Assistant integration for sipgate.io call webhooks."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

import voluptuous as vol
from homeassistant.components import webhook as ha_webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, CONF_WEBHOOK_ID, Platform
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
    SipgateAuthorizationError,
    SipgateClient,
    SipgateConnectionError,
    SipgateCredentialFormatError,
)
from .call_state import SipgateCallState
from .const import (
    ATTR_ANNOUNCEMENT,
    ATTR_CALLER_ID,
    ATTR_CALL_ID,
    ATTR_DEVICE_ID,
    ATTR_FROM,
    ATTR_TO,
    CONF_PUBLIC_URL,
    CONF_TOKEN_ID,
    DOMAIN,
    NAME,
    SERVICE_CLICK_TO_CALL,
    SERVICE_HANG_UP,
    SERVICE_START_RECORDING,
    SERVICE_STOP_RECORDING,
)
from .coordinator import SipgateHistoryCoordinator
from .helpers import build_webhook_url
from .webhook import async_handle_webhook

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = (Platform.BINARY_SENSOR, Platform.SENSOR)


@dataclass(slots=True)
class SipgateRuntimeData:
    """Runtime data for the configured sipgate account."""

    client: SipgateClient
    webhook_url: str
    call_state: SipgateCallState
    history_coordinator: SipgateHistoryCoordinator


def _get_runtime(hass: HomeAssistant) -> SipgateRuntimeData:
    """Return the single loaded sipgate runtime."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("sipgate.io is not configured or loaded")

    runtime = entries[0].runtime_data
    if not isinstance(runtime, SipgateRuntimeData):
        raise ServiceValidationError("sipgate.io is not ready")
    return runtime


def _raise_service_error(err: Exception) -> None:
    """Translate API exceptions into Home Assistant action errors."""
    if isinstance(err, SipgateAuthenticationError):
        raise HomeAssistantError(
            "sipgate rejected the configured credentials"
        ) from err
    if isinstance(err, SipgateAuthorizationError):
        raise HomeAssistantError(
            "The sipgate token does not have permission for this action"
        ) from err
    if isinstance(err, SipgateConnectionError):
        raise HomeAssistantError("Could not connect to sipgate") from err
    if isinstance(err, SipgateApiError):
        raise HomeAssistantError(str(err)) from err
    raise err


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the sipgate.io integration."""
    del config

    async def async_hang_up(call: ServiceCall) -> None:
        runtime = _get_runtime(hass)
        try:
            await runtime.client.async_hang_up(call.data[ATTR_CALL_ID])
        except (
            SipgateApiError,
            SipgateAuthenticationError,
            SipgateAuthorizationError,
            SipgateConnectionError,
        ) as err:
            _raise_service_error(err)

    async def async_start_recording(call: ServiceCall) -> None:
        runtime = _get_runtime(hass)
        call_id = call.data[ATTR_CALL_ID]
        try:
            await runtime.client.async_set_recording(
                call_id,
                recording=True,
                announcement=call.data[ATTR_ANNOUNCEMENT],
            )
        except (
            SipgateApiError,
            SipgateAuthenticationError,
            SipgateAuthorizationError,
            SipgateConnectionError,
        ) as err:
            _raise_service_error(err)
        runtime.call_state.set_recording(call_id, True)

    async def async_stop_recording(call: ServiceCall) -> None:
        runtime = _get_runtime(hass)
        call_id = call.data[ATTR_CALL_ID]
        try:
            await runtime.client.async_set_recording(
                call_id,
                recording=False,
                announcement=call.data[ATTR_ANNOUNCEMENT],
            )
        except (
            SipgateApiError,
            SipgateAuthenticationError,
            SipgateAuthorizationError,
            SipgateConnectionError,
        ) as err:
            _raise_service_error(err)
        runtime.call_state.set_recording(call_id, False)

    async def async_click_to_call(call: ServiceCall) -> None:
        runtime = _get_runtime(hass)
        try:
            session_id = await runtime.client.async_click_to_call(
                from_endpoint=call.data[ATTR_FROM],
                to_number=call.data[ATTR_TO],
                device_id=call.data.get(ATTR_DEVICE_ID),
                caller_id=call.data.get(ATTR_CALLER_ID),
            )
        except (
            SipgateApiError,
            SipgateAuthenticationError,
            SipgateAuthorizationError,
            SipgateConnectionError,
        ) as err:
            _raise_service_error(err)

        if session_id:
            runtime.call_state.started(
                {
                    "call_id": session_id,
                    "direction": "out",
                    "from": call.data[ATTR_FROM],
                    "to": call.data[ATTR_TO],
                    "display": call.data[ATTR_TO],
                    "known": False,
                    "anonymous": False,
                }
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_HANG_UP,
        async_hang_up,
        schema=vol.Schema({vol.Required(ATTR_CALL_ID): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_RECORDING,
        async_start_recording,
        schema=vol.Schema(
            {
                vol.Required(ATTR_CALL_ID): cv.string,
                vol.Optional(ATTR_ANNOUNCEMENT, default=True): cv.boolean,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_RECORDING,
        async_stop_recording,
        schema=vol.Schema(
            {
                vol.Required(ATTR_CALL_ID): cv.string,
                vol.Optional(ATTR_ANNOUNCEMENT, default=False): cv.boolean,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLICK_TO_CALL,
        async_click_to_call,
        schema=vol.Schema(
            {
                vol.Required(ATTR_FROM): cv.string,
                vol.Required(ATTR_TO): cv.string,
                vol.Optional(ATTR_DEVICE_ID): cv.string,
                vol.Optional(ATTR_CALLER_ID): cv.string,
            }
        ),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up sipgate.io from a config entry."""
    try:
        client = SipgateClient(
            async_get_clientsession(hass),
            entry.data[CONF_TOKEN_ID],
            entry.data[CONF_TOKEN],
        )
    except SipgateCredentialFormatError as err:
        raise ConfigEntryAuthFailed("Invalid sipgate credential format") from err

    try:
        await client.async_validate_credentials()
    except (SipgateAuthenticationError, SipgateAuthorizationError) as err:
        raise ConfigEntryAuthFailed("Invalid sipgate credentials") from err
    except SipgateConnectionError as err:
        raise ConfigEntryNotReady("Could not connect to sipgate") from err
    except SipgateApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    webhook_id = entry.data[CONF_WEBHOOK_ID]
    webhook_url = build_webhook_url(entry.data[CONF_PUBLIC_URL], webhook_id)
    call_state = SipgateCallState()
    history_coordinator = SipgateHistoryCoordinator(hass, client)
    entry.runtime_data = SipgateRuntimeData(
        client=client,
        webhook_url=webhook_url,
        call_state=call_state,
        history_coordinator=history_coordinator,
    )

    ha_webhook.async_register(
        hass,
        DOMAIN,
        NAME,
        webhook_id,
        partial(async_handle_webhook, entry=entry, webhook_url=webhook_url),
        allowed_methods=("POST",),
    )
    entry.async_on_unload(partial(ha_webhook.async_unregister, hass, webhook_id))
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options or connection data change."""
    await hass.config_entries.async_reload(entry.entry_id)
