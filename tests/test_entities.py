"""Tests for sipgate call-state and history entities."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.sipgate_ha.const import API_BASE_URL, DOMAIN


async def _setup_entry(hass: HomeAssistant, entry, aioclient_mock) -> None:
    """Set up the integration and its entity platforms."""
    aioclient_mock.get(f"{API_BASE_URL}/account", json={"sub": "w0"})
    aioclient_mock.get(
        f"{API_BASE_URL}/history",
        repeat=True,
        json={
            "items": [
                {
                    "id": "history-1",
                    "type": "CALL",
                    "callId": "old-call",
                    "source": "+442071111111",
                    "target": "+442072222222",
                    "direction": "INCOMING",
                    "callStatus": "SUCCESS",
                    "duration": 30,
                    "recordings": [],
                }
            ],
            "totalCount": 1,
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities_follow_webhooks(
    hass: HomeAssistant, hass_client, mock_config_entry, aioclient_mock
) -> None:
    """Push events update active-call, state, caller and last-call entities."""
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    registry = er.async_get(hass)

    active_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{mock_config_entry.entry_id}_call_active"
    )
    state_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{mock_config_entry.entry_id}_call_state"
    )
    caller_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{mock_config_entry.entry_id}_last_caller"
    )
    last_call_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{mock_config_entry.entry_id}_last_call"
    )
    history_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{mock_config_entry.entry_id}_recent_calls"
    )
    api_today_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{mock_config_entry.entry_id}_api_requests_today"
    )
    api_lifetime_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{mock_config_entry.entry_id}_api_requests_lifetime"
    )

    assert all(
        (
            active_id,
            state_id,
            caller_id,
            last_call_id,
            history_id,
            api_today_id,
            api_lifetime_id,
        )
    )
    assert hass.states.get(api_today_id).state == "2"
    assert hass.states.get(api_lifetime_id).state == "2"
    client = await hass_client()

    await client.post(
        "/api/webhook/test-webhook-id",
        data={
            "event": "newCall",
            "from": "442071234567",
            "to": "442079876543",
            "direction": "in",
            "callId": "call-123",
        },
    )
    await hass.async_block_till_done()

    assert hass.states.get(active_id).state == "on"
    assert hass.states.get(state_id).state == "ringing"
    assert hass.states.get(caller_id).state == "+442071234567"

    await client.post(
        "/api/webhook/test-webhook-id",
        data={
            "event": "answer",
            "callId": "call-123",
            "direction": "in",
            "user": "Alice",
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get(state_id).state == "answered"

    await client.post(
        "/api/webhook/test-webhook-id",
        data={
            "event": "hangup",
            "callId": "call-123",
            "direction": "in",
            "cause": "normalClearing",
        },
    )
    await hass.async_block_till_done()

    assert hass.states.get(active_id).state == "off"
    assert hass.states.get(state_id).state == "idle"
    assert hass.states.get(last_call_id).state == "normalClearing"
    assert hass.states.get(history_id).state == "1"
    assert hass.states.get(history_id).attributes["calls"][0]["callId"] == "old-call"
    assert hass.states.get(api_today_id).state == "3"
    assert hass.states.get(api_lifetime_id).state == "3"
