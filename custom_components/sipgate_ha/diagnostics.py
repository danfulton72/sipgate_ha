"""Diagnostics support for sipgate.io."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant

from .const import CONF_CONTACTS, CONF_TOKEN_ID

TO_REDACT = {CONF_TOKEN, CONF_WEBHOOK_ID, CONF_CONTACTS}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return privacy-aware diagnostics for a config entry."""
    del hass
    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "token_id_present": bool(entry.data.get(CONF_TOKEN_ID)),
    }
