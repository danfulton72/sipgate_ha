"""Integration-level tests for sipgate.io webhooks and actions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.sipgate_ha.const import (
    API_BASE_URL,
    ATTR_ANNOUNCEMENT,
    ATTR_CALL_ID,
    ATTR_FROM,
    ATTR_MESSAGE,
    ATTR_RECIPIENT,
    ATTR_SMS_ID,
    ATTR_TO,
    CONF_CONTACTS,
    CONF_HISTORY_REFRESH_MINUTES,
    CONF_INCLUDE_OUTGOING,
    CONF_SIGNIFICANT_DIGITS,
    DOMAIN,
    EVENT_CALL_ANSWERED,
    EVENT_CALL_ENDED,
    EVENT_CALL_STARTED,
    SERVICE_CLICK_TO_CALL,
    SERVICE_HANG_UP,
    SERVICE_SEND_SMS,
    SERVICE_START_RECORDING,
    SERVICE_STOP_RECORDING,
)


async def _setup_entry(hass: HomeAssistant, entry, aioclient_mock) -> None:
    """Set up a config entry with successful sipgate validation."""
    aioclient_mock.get(f"{API_BASE_URL}/account", json={"sub": "w0"})
    aioclient_mock.get(
        f"{API_BASE_URL}/history",
        json={"items": [], "totalCount": 0},
        repeat=True,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_new_call_webhook(
    hass: HomeAssistant, hass_client, mock_config_entry, aioclient_mock
) -> None:
    """Incoming calls fire the legacy-compatible HA event and return XML."""
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            CONF_CONTACTS: "+442071234567=Mum",
            CONF_SIGNIFICANT_DIGITS: 9,
            CONF_INCLUDE_OUTGOING: False,
        },
    )
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    events = async_capture_events(hass, EVENT_CALL_STARTED)
    client = await hass_client()

    response = await client.post(
        "/api/webhook/test-webhook-id",
        data=[
            ("event", "newCall"),
            ("from", "442071234567"),
            ("to", "441234567890"),
            ("direction", "in"),
            ("callId", "call-123"),
            ("user[]", "Alice"),
            ("userId[]", "w0"),
            ("fullUserId[]", "123w0"),
        ],
    )

    assert response.status == 200
    assert response.content_type == "application/xml"
    body = await response.text()
    assert 'onAnswer="https://ha.example.com/api/webhook/test-webhook-id"' in body
    assert 'onHangup="https://ha.example.com/api/webhook/test-webhook-id"' in body

    await hass.async_block_till_done()
    assert len(events) == 1
    data = events[0].data
    assert data["call_id"] == "call-123"
    assert data["from"] == "+442071234567"
    assert data["name"] == "Mum"
    assert data["display"] == "Mum (+442071234567)"
    assert data["known"] is True
    assert data["users"] == ["Alice"]
    assert data["user_ids"] == ["w0"]


async def test_answer_and_hangup_webhooks(
    hass: HomeAssistant, hass_client, mock_config_entry, aioclient_mock
) -> None:
    """Follow-up events use the same webhook endpoint."""
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    answer_events = async_capture_events(hass, EVENT_CALL_ANSWERED)
    ended_events = async_capture_events(hass, EVENT_CALL_ENDED)
    client = await hass_client()

    response = await client.post(
        "/api/webhook/test-webhook-id",
        data={
            "event": "answer",
            "callId": "call-123",
            "direction": "in",
            "user": "Alice",
            "answeringNumber": "442079999999",
        },
    )
    assert response.status == 204

    response = await client.post(
        "/api/webhook/test-webhook-id",
        data={
            "event": "hangup",
            "callId": "call-123",
            "direction": "in",
            "cause": "normalClearing",
        },
    )
    assert response.status == 204

    await hass.async_block_till_done()
    assert answer_events[0].data["answered_by"] == "Alice"
    assert answer_events[0].data["answering_number"] == "+442079999999"
    assert ended_events[0].data["cause"] == "normalClearing"


async def test_outgoing_ignored_by_default(
    hass: HomeAssistant, hass_client, mock_config_entry, aioclient_mock
) -> None:
    """Outgoing newCall events do not fire unless explicitly enabled."""
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    events = async_capture_events(hass, EVENT_CALL_STARTED)
    client = await hass_client()

    response = await client.post(
        "/api/webhook/test-webhook-id",
        data={
            "event": "newCall",
            "from": "442071234567",
            "to": "441234567890",
            "direction": "out",
            "callId": "call-out",
        },
    )
    assert response.status == 200
    await hass.async_block_till_done()
    assert events == []


async def test_hang_up_action(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """The native Home Assistant action calls sipgate RTCM directly."""
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    aioclient_mock.delete(f"{API_BASE_URL}/calls/call-123", status=204)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_HANG_UP,
        {ATTR_CALL_ID: "call-123"},
        blocking=True,
    )


async def test_outgoing_enabled(
    hass: HomeAssistant, hass_client, mock_config_entry, aioclient_mock
) -> None:
    """Outgoing newCall events can be enabled in options."""
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_INCLUDE_OUTGOING: True}
    )
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    events = async_capture_events(hass, EVENT_CALL_STARTED)
    client = await hass_client()

    response = await client.post(
        "/api/webhook/test-webhook-id",
        data={
            "event": "newCall",
            "from": "442071234567",
            "to": "441234567890",
            "direction": "out",
            "callId": "call-out",
        },
    )

    assert response.status == 200
    await hass.async_block_till_done()
    assert events[0].data["call_id"] == "call-out"


async def test_unknown_webhook_event(
    hass: HomeAssistant, hass_client, mock_config_entry, aioclient_mock
) -> None:
    """Unknown sipgate event names are acknowledged without firing call events."""
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    started = async_capture_events(hass, EVENT_CALL_STARTED)
    client = await hass_client()

    response = await client.post(
        "/api/webhook/test-webhook-id", data={"event": "somethingElse"}
    )

    assert response.status == 204
    await hass.async_block_till_done()
    assert started == []


async def test_recording_actions(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """Start and stop recording call the RTCM recording endpoint."""
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    aioclient_mock.put(f"{API_BASE_URL}/calls/call-123/recording", status=204)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_START_RECORDING,
        {ATTR_CALL_ID: "call-123", ATTR_ANNOUNCEMENT: True},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_STOP_RECORDING,
        {ATTR_CALL_ID: "call-123", ATTR_ANNOUNCEMENT: False},
        blocking=True,
    )


async def test_click_to_call_action(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """Click-to-call uses the sessions API and creates outgoing call state."""
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    aioclient_mock.post(
        f"{API_BASE_URL}/sessions/calls", json={"sessionId": "session-123"}
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLICK_TO_CALL,
        {
            ATTR_FROM: "e14",
            ATTR_TO: "+442071234567",
        },
        blocking=True,
    )

    runtime = mock_config_entry.runtime_data
    assert runtime.call_state.current_call["call_id"] == "session-123"
    assert runtime.call_state.state == "ringing"


async def test_recording_permission_error(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """RTCM permission failures become useful Home Assistant action errors."""
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    aioclient_mock.put(f"{API_BASE_URL}/calls/call-123/recording", status=403)

    with pytest.raises(HomeAssistantError, match="permission"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_START_RECORDING,
            {ATTR_CALL_ID: "call-123", ATTR_ANNOUNCEMENT: True},
            blocking=True,
        )


async def test_send_sms_action(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """Send SMS calls the sessions SMS endpoint."""
    await _setup_entry(hass, mock_config_entry, aioclient_mock)
    aioclient_mock.post(
        f"{API_BASE_URL}/sessions/sms",
        json={"sessionId": "sms-session-123"},
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_SMS,
        {
            ATTR_SMS_ID: "s0",
            ATTR_RECIPIENT: "+447700900123",
            ATTR_MESSAGE: "Hello from Home Assistant",
        },
        blocking=True,
    )


async def test_history_polling_disabled_by_default(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """History has no periodic polling interval unless explicitly configured."""
    await _setup_entry(hass, mock_config_entry, aioclient_mock)

    assert mock_config_entry.runtime_data.history_coordinator.update_interval is None


async def test_history_polling_interval_option(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """A positive history refresh option enables fallback polling."""
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_HISTORY_REFRESH_MINUTES: 15},
    )
    await _setup_entry(hass, mock_config_entry, aioclient_mock)

    coordinator = mock_config_entry.runtime_data.history_coordinator
    assert coordinator.update_interval == timedelta(minutes=15)
