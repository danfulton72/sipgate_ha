"""Tests for privacy-aware diagnostics."""

from __future__ import annotations

from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant

from custom_components.sipgate_ha.const import CONF_CONTACTS
from custom_components.sipgate_ha.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redact_secrets(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Credentials, webhook IDs, and caller mappings are redacted."""
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_CONTACTS: "+442071234567=Mum"}
    )
    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    data = result["entry"]["data"]
    options = result["entry"]["options"]
    assert data["token"] == "**REDACTED**"
    assert data[CONF_WEBHOOK_ID] == "**REDACTED**"
    assert options[CONF_CONTACTS] == "**REDACTED**"
    assert result["token_id_present"] is True
