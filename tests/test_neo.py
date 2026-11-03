"""Tests for sipgate Neo support: detection, channel events and click-to-dial."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.sipgate_ha.account_type import (
    SipgateAccountType,
    parse_channel_ids,
)
from custom_components.sipgate_ha.api import SipgateApiError, SipgateClient
from custom_components.sipgate_ha.const import (
    ACCOUNT_TYPE_AUTO,
    ACCOUNT_TYPE_CLASSIC,
    ACCOUNT_TYPE_NEO,
    API_BASE_URL,
    ATTR_CHANNEL_ID,
    ATTR_FROM,
    ATTR_TO,
    CLASSIC_RECHECK_SECONDS,
    CONF_ACCOUNT_TYPE,
    CONF_CHANNEL_IDS,
    CONF_PUBLIC_URL,
    CONF_TOKEN_ID,
    DOMAIN,
    EVENT_CALL_STARTED,
    SERVICE_CLICK_TO_CALL,
)
from custom_components.sipgate_ha.diagnostics import async_get_config_entry_diagnostics


def _client(hass: HomeAssistant) -> SipgateClient:
    return SipgateClient(async_get_clientsession(hass), "token-id", "secret")


async def _setup(hass: HomeAssistant, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _recent_calls_entity(hass: HomeAssistant, entry) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_recent_calls"
    )
    assert entity_id is not None
    return entity_id


# --- API client ------------------------------------------------------------


async def test_get_channels_parses_wrapped_and_bare_lists(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Channels are read from an items wrapper and malformed rows are skipped."""
    aioclient_mock.get(
        f"{API_BASE_URL}/channels",
        json={
            "items": [
                {"id": "c0", "alias": "Main line"},
                {"channelId": "c1", "name": "Support"},
                {"id": "c2"},
                {"alias": "no id"},
                "junk",
            ]
        },
    )

    channels = await _client(hass).async_get_channels()

    assert channels == [
        {"id": "c0", "name": "Main line"},
        {"id": "c1", "name": "Support"},
        {"id": "c2", "name": "c2"},
    ]


async def test_get_channels_unexpected_payload(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A payload without a channel list is an API error."""
    aioclient_mock.get(f"{API_BASE_URL}/channels", json={"unexpected": True})

    with pytest.raises(SipgateApiError):
        await _client(hass).async_get_channels()


async def test_get_channel_events_normalizes(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Channel events keep useful fields, default recordings and tag the channel."""
    aioclient_mock.get(
        f"{API_BASE_URL}/channels/c%2F0/events",
        json=[
            {
                "id": "event-1",
                "callId": "call-1",
                "direction": "INCOMING",
                "created": "2026-11-17T09:00:00Z",
                "recordings": [{"id": "rec-1", "url": "https://example.invalid/r"}],
                "secretInternal": "dropped",
            },
            {"id": "event-2", "channelId": "other"},
            "junk",
        ],
    )

    events = await _client(hass).async_get_channel_events("c/0", 10)

    assert events[0]["channelId"] == "c/0"
    assert events[0]["recordings"][0]["id"] == "rec-1"
    assert "secretInternal" not in events[0]
    assert events[1] == {"id": "event-2", "channelId": "other", "recordings": []}
    assert len(events) == 2


async def test_get_channel_events_unexpected_payload(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A payload without an event list is an API error."""
    aioclient_mock.get(f"{API_BASE_URL}/channels/c0/events", json={"nope": 1})

    with pytest.raises(SipgateApiError):
        await _client(hass).async_get_channel_events("c0", 10)


async def test_neo_click_to_call(hass: HomeAssistant, aioclient_mock) -> None:
    """Neo click-to-dial posts to /calls with an optional channel."""
    aioclient_mock.post(f"{API_BASE_URL}/calls", json={"callId": "neo-call-1"})

    call_id = await _client(hass).async_neo_click_to_call(
        from_endpoint="e14",
        to_number="+442071234567",
        device_id="e14",
        caller_id="+442079876543",
        channel_id="c0",
    )

    assert call_id == "neo-call-1"
    _, _, body, _ = aioclient_mock.mock_calls[-1]
    assert body == {
        "caller": "e14",
        "callee": "+442071234567",
        "deviceId": "e14",
        "callerId": "+442079876543",
        "channelId": "c0",
    }


async def test_neo_click_to_call_without_id(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """An empty Neo click-to-dial response returns no call ID."""
    aioclient_mock.post(f"{API_BASE_URL}/calls", status=204)

    assert (
        await _client(hass).async_neo_click_to_call(
            from_endpoint="e14", to_number="+442071234567"
        )
        is None
    )


# --- Account-type detection ------------------------------------------------


def test_parse_channel_ids() -> None:
    """Channel IDs accept commas and whitespace and drop duplicates."""
    assert parse_channel_ids(None) == []
    assert parse_channel_ids("") == []
    assert parse_channel_ids(" c0, c1 c0,\nc2 ") == ["c0", "c1", "c2"]


async def test_forced_account_types(hass: HomeAssistant) -> None:
    """Forced Classic or Neo never contacts sipgate."""
    client = _client(hass)
    assert await SipgateAccountType(client, ACCOUNT_TYPE_NEO, []).async_is_neo()
    assert not await SipgateAccountType(client, ACCOUNT_TYPE_CLASSIC, []).async_is_neo()


@pytest.mark.parametrize(
    ("kwargs", "detail"),
    [
        ({"status": 404}, "HTTP 404"),
        ({"status": 403}, "403"),
        ({"json": {"items": []}}, "none"),
    ],
)
async def test_auto_detects_classic(
    hass: HomeAssistant, aioclient_mock, kwargs, detail
) -> None:
    """Missing or empty channels mean a Classic account."""
    aioclient_mock.get(f"{API_BASE_URL}/channels", **kwargs)
    resolver = SipgateAccountType(_client(hass), ACCOUNT_TYPE_AUTO, [])

    assert not await resolver.async_is_neo()
    assert resolver.detected == ACCOUNT_TYPE_CLASSIC
    assert detail in resolver.detection_detail


async def test_auto_connection_error_retries(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A connection failure is not cached as a detection result."""
    aioclient_mock.get(f"{API_BASE_URL}/channels", exc=TimeoutError)
    resolver = SipgateAccountType(_client(hass), ACCOUNT_TYPE_AUTO, [])

    assert not await resolver.async_is_neo()
    assert resolver.detected is None

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_BASE_URL}/channels", json={"items": [{"id": "c0"}]})
    assert await resolver.async_is_neo()


async def test_auto_rechecks_classic_after_interval(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A Classic result is re-checked so the Neo upgrade is noticed live."""
    aioclient_mock.get(f"{API_BASE_URL}/channels", status=404)
    resolver = SipgateAccountType(_client(hass), ACCOUNT_TYPE_AUTO, [])
    module = "custom_components.sipgate_ha.account_type.time.monotonic"

    with patch(module, return_value=1000.0):
        assert not await resolver.async_is_neo()
    with patch(module, return_value=1000.0 + CLASSIC_RECHECK_SECONDS - 1):
        assert not await resolver.async_is_neo()
    assert aioclient_mock.call_count == 1

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_BASE_URL}/channels", json=[{"id": "c0"}])
    with patch(module, return_value=1000.0 + CLASSIC_RECHECK_SECONDS + 1):
        assert await resolver.async_is_neo()
    # Neo is sticky: no further probes.
    assert await resolver.async_is_neo()
    assert aioclient_mock.call_count == 1


async def test_channel_ids_configured_or_discovered(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Configured channels win; otherwise up to five discovered channels are used."""
    client = _client(hass)
    assert await SipgateAccountType(
        client, ACCOUNT_TYPE_NEO, ["c9"]
    ).async_channel_ids() == ["c9"]

    aioclient_mock.get(
        f"{API_BASE_URL}/channels", json=[{"id": f"c{i}"} for i in range(7)]
    )
    resolver = SipgateAccountType(client, ACCOUNT_TYPE_NEO, [])
    assert await resolver.async_channel_ids() == ["c0", "c1", "c2", "c3", "c4"]
    # Cached after the first lookup.
    await resolver.async_channel_ids()
    assert aioclient_mock.call_count == 1


# --- Integration ------------------------------------------------------------


async def test_neo_recent_calls_merge_channels(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """On Neo, Recent calls merges events from all channels, newest first."""
    aioclient_mock.get(f"{API_BASE_URL}/account", json={"sub": "w0"})
    aioclient_mock.get(
        f"{API_BASE_URL}/channels",
        json={"items": [{"id": "c0", "alias": "Main"}, {"id": "c1"}]},
    )
    aioclient_mock.get(
        f"{API_BASE_URL}/channels/c0/events",
        json={
            "items": [
                {"id": "a", "callId": "old", "created": "2026-11-17T08:00:00Z"},
                {"id": "b", "callId": "newest", "created": "2026-11-17T10:00:00Z"},
            ]
        },
    )
    aioclient_mock.get(
        f"{API_BASE_URL}/channels/c1/events",
        json={"items": [{"id": "c", "callId": "mid", "timestamp": "2026-11-17T09"}]},
    )

    await _setup(hass, mock_config_entry)

    state = hass.states.get(_recent_calls_entity(hass, mock_config_entry))
    assert state.state == "3"
    assert [call["callId"] for call in state.attributes["calls"]] == [
        "newest",
        "mid",
        "old",
    ]
    assert not any("/history" in str(url) for _, url, _, _ in aioclient_mock.mock_calls)

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert diagnostics["account_type"]["detected"] == ACCOUNT_TYPE_NEO
    assert diagnostics["account_type"]["discovered_channels"][0] == {
        "id": "c0",
        "name": "Main",
    }


async def test_neo_configured_channels_only(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """Configured channel IDs are the only channels read on forced Neo."""
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_ACCOUNT_TYPE: ACCOUNT_TYPE_NEO, CONF_CHANNEL_IDS: "c5"},
    )
    aioclient_mock.get(f"{API_BASE_URL}/account", json={"sub": "w0"})
    aioclient_mock.get(
        f"{API_BASE_URL}/channels/c5/events", json={"items": [{"id": "x"}]}
    )

    await _setup(hass, mock_config_entry)

    assert hass.states.get(_recent_calls_entity(hass, mock_config_entry)).state == "1"
    assert aioclient_mock.call_count == 2


async def test_neo_without_channels_marks_history_unavailable(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """Forced Neo with no visible channels leaves Recent calls unavailable."""
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_ACCOUNT_TYPE: ACCOUNT_TYPE_NEO}
    )
    aioclient_mock.get(f"{API_BASE_URL}/account", json={"sub": "w0"})
    aioclient_mock.get(f"{API_BASE_URL}/channels", json={"items": []})

    await _setup(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data.history_coordinator
    assert coordinator.last_update_success is False
    assert "No sipgate Neo channels" in str(coordinator.last_exception)


async def test_neo_channel_membership_error(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """A 403 on channel events explains the channel-membership requirement."""
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_ACCOUNT_TYPE: ACCOUNT_TYPE_NEO, CONF_CHANNEL_IDS: "c0"},
    )
    aioclient_mock.get(f"{API_BASE_URL}/account", json={"sub": "w0"})
    aioclient_mock.get(f"{API_BASE_URL}/channels/c0/events", status=403)

    await _setup(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data.history_coordinator
    assert "member of each channel" in str(coordinator.last_exception)


async def test_neo_click_to_call_action(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """The click-to-call action uses POST /calls on Neo and tracks the call."""
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_ACCOUNT_TYPE: ACCOUNT_TYPE_NEO, CONF_CHANNEL_IDS: "c0"},
    )
    aioclient_mock.get(f"{API_BASE_URL}/account", json={"sub": "w0"})
    aioclient_mock.get(f"{API_BASE_URL}/channels/c0/events", json={"items": []})
    await _setup(hass, mock_config_entry)
    aioclient_mock.post(f"{API_BASE_URL}/calls", json={"callId": "neo-call-1"})

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLICK_TO_CALL,
        {ATTR_FROM: "e14", ATTR_TO: "+442071234567", ATTR_CHANNEL_ID: "c0"},
        blocking=True,
    )

    _, url, body, _ = aioclient_mock.mock_calls[-1]
    assert str(url) == f"{API_BASE_URL}/calls"
    assert body["channelId"] == "c0"
    runtime = mock_config_entry.runtime_data
    assert runtime.call_state.current_call["call_id"] == "neo-call-1"


async def test_webhook_captures_channel_id(
    hass: HomeAssistant, hass_client, mock_config_entry, aioclient_mock
) -> None:
    """Push API v2 channelId values are passed through to HA events."""
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_ACCOUNT_TYPE: ACCOUNT_TYPE_NEO, CONF_CHANNEL_IDS: "c0"},
    )
    aioclient_mock.get(f"{API_BASE_URL}/account", json={"sub": "w0"})
    aioclient_mock.get(f"{API_BASE_URL}/channels/c0/events", json={"items": []})
    await _setup(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_CALL_STARTED)
    client = await hass_client()

    response = await client.post(
        "/api/webhook/test-webhook-id",
        data={
            "event": "newCall",
            "from": "442071234567",
            "to": "441234567890",
            "direction": "in",
            "callId": "call-9",
            "channelId": "c0",
        },
    )

    assert response.status == 200
    await hass.async_block_till_done()
    assert events[0].data["channel_id"] == "c0"


async def test_http_public_url_raises_repair_issue(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """Legacy HTTP URLs raise a repair issue because sipgate requires HTTPS."""
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_PUBLIC_URL: "http://ha.example.com"},
        options={CONF_ACCOUNT_TYPE: ACCOUNT_TYPE_CLASSIC},
    )
    aioclient_mock.get(f"{API_BASE_URL}/account", json={"sub": "w0"})
    aioclient_mock.get(f"{API_BASE_URL}/history", json={"items": []})

    await _setup(hass, mock_config_entry)

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "insecure_public_url") is not None

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_PUBLIC_URL: "https://ha.example.com"},
    )
    await _setup(hass, mock_config_entry)
    assert registry.async_get_issue(DOMAIN, "insecure_public_url") is None


async def test_user_flow_rejects_http(hass: HomeAssistant) -> None:
    """New setups must use an HTTPS public URL."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TOKEN_ID: "token-test-0",
            CONF_TOKEN: "secret-token",
            CONF_PUBLIC_URL: "http://ha.example.com",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PUBLIC_URL: "invalid_url"}


async def test_options_flow_account_type(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """The platform and channel IDs are configurable options."""
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "include_outgoing": False,
            "significant_digits": 9,
            "history_refresh_minutes": 0,
            CONF_ACCOUNT_TYPE: ACCOUNT_TYPE_NEO,
            CONF_CHANNEL_IDS: "c0, c1",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ACCOUNT_TYPE] == ACCOUNT_TYPE_NEO
    assert result["data"][CONF_CHANNEL_IDS] == "c0, c1"
