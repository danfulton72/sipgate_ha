"""Tests for sipgate call-state and history entities."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.sipgate_ha.const import (
    API_BASE_URL,
    DOMAIN,
    LEGACY_CONF_AUTO_RECORD_ANNOUNCEMENT,
    LEGACY_CONF_AUTO_RECORD_CALLS,
)


async def _setup_entry(hass: HomeAssistant, entry, aioclient_mock) -> None:
    """Set up the integration and its entity platforms."""
    aioclient_mock.get(f"{API_BASE_URL}/account", json={"sub": "w0"})
    aioclient_mock.get(
        f"{API_BASE_URL}/history",
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


async def test_api_usage_persists_across_reload(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """Lifetime and daily API usage survive an integration reload."""
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    runtime = mock_config_entry.runtime_data
    assert runtime.api_usage.today == 2
    assert runtime.api_usage.lifetime == 2

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    runtime = mock_config_entry.runtime_data
    assert runtime.api_usage.today == 4
    assert runtime.api_usage.lifetime == 4


async def test_recording_switches_control_runtime_preferences(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """Recording and announcement preferences are exposed as config switches."""
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    registry = er.async_get(hass)

    entity_ids = {
        key: registry.async_get_entity_id(
            "switch", DOMAIN, f"{mock_config_entry.entry_id}_{key}"
        )
        for key in (
            "record_incoming_calls",
            "announce_incoming_recording",
            "record_outgoing_calls",
            "announce_outgoing_recording",
        )
    }
    assert all(entity_ids.values())
    assert all(
        hass.states.get(entity_id).state == STATE_OFF
        for entity_id in entity_ids.values()
    )

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": entity_ids["record_incoming_calls"]},
        blocking=True,
    )
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": entity_ids["announce_outgoing_recording"]},
        blocking=True,
    )

    assert hass.states.get(entity_ids["record_incoming_calls"]).state == STATE_ON
    assert (
        hass.states.get(entity_ids["announce_outgoing_recording"]).state == STATE_ON
    )

    preferences = mock_config_entry.runtime_data.recording_preferences
    assert preferences.record_incoming is True
    assert preferences.announce_incoming is False
    assert preferences.record_outgoing is False
    assert preferences.announce_outgoing is True


async def test_legacy_recording_options_seed_switch_defaults(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """Earlier branch options seed all four switches until switch state is saved."""
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            LEGACY_CONF_AUTO_RECORD_CALLS: True,
            LEGACY_CONF_AUTO_RECORD_ANNOUNCEMENT: True,
        },
    )
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    registry = er.async_get(hass)

    for key in (
        "record_incoming_calls",
        "announce_incoming_recording",
        "record_outgoing_calls",
        "announce_outgoing_recording",
    ):
        entity_id = registry.async_get_entity_id(
            "switch", DOMAIN, f"{mock_config_entry.entry_id}_{key}"
        )
        assert entity_id is not None
        assert hass.states.get(entity_id).state == STATE_ON
