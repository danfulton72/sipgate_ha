"""Tests for the minimal sipgate REST client."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.sipgate_ha.api import (
    SipgateApiError,
    SipgateAuthenticationError,
    SipgateAuthorizationError,
    SipgateClient,
    SipgateCredentialFormatError,
)
from custom_components.sipgate_ha.const import API_BASE_URL


async def test_validate_credentials(hass: HomeAssistant, aioclient_mock) -> None:
    """A successful account request validates the PAT."""
    aioclient_mock.get(f"{API_BASE_URL}/account", json={"sub": "w0"})
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    await client.async_validate_credentials()


async def test_authentication_error(hass: HomeAssistant, aioclient_mock) -> None:
    """401 responses are authentication errors."""
    aioclient_mock.get(f"{API_BASE_URL}/account", status=401)
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    with pytest.raises(SipgateAuthenticationError):
        await client.async_validate_credentials()


async def test_api_error(hass: HomeAssistant, aioclient_mock) -> None:
    """Other HTTP failures retain their status and a bounded response body."""
    aioclient_mock.get(f"{API_BASE_URL}/account", status=500, text="server error")
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    with pytest.raises(SipgateApiError) as err:
        await client.async_validate_credentials()

    assert err.value.status == 500
    assert "server error" in str(err.value)


async def test_hang_up_quotes_call_id(hass: HomeAssistant, aioclient_mock) -> None:
    """Call IDs are safely encoded in the REST path."""
    aioclient_mock.delete(f"{API_BASE_URL}/calls/id%2Fwith%20space", status=204)
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    await client.async_hang_up("id/with space")


async def test_authorization_error(hass: HomeAssistant, aioclient_mock) -> None:
    """403 responses are authorization errors."""
    aioclient_mock.delete(f"{API_BASE_URL}/calls/call-123", status=403)
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    with pytest.raises(SipgateAuthorizationError):
        await client.async_hang_up("call-123")


async def test_invalid_token_id_format(hass: HomeAssistant) -> None:
    """Token IDs containing a colon are rejected before any request is made."""
    with pytest.raises(SipgateCredentialFormatError) as err:
        SipgateClient(
            async_get_clientsession(hass),
            "token-id:secret",
            "secret",
        )

    assert err.value.field == "token_id"


async def test_empty_token_rejected(hass: HomeAssistant) -> None:
    """An empty PAT secret is rejected before any request is made."""
    with pytest.raises(SipgateCredentialFormatError) as err:
        SipgateClient(async_get_clientsession(hass), "token-id", "")

    assert err.value.field == "token"


async def test_recording_control(hass: HomeAssistant, aioclient_mock) -> None:
    """Recording control uses the RTCM recording endpoint."""
    aioclient_mock.put(f"{API_BASE_URL}/calls/call-123/recording", status=204)
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    await client.async_set_recording("call-123", recording=True, announcement=True)


async def test_click_to_call(hass: HomeAssistant, aioclient_mock) -> None:
    """Click-to-call returns the sipgate session ID."""
    aioclient_mock.post(
        f"{API_BASE_URL}/sessions/calls", json={"sessionId": "session-123"}
    )
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    session_id = await client.async_click_to_call(
        from_endpoint="e14",
        to_number="+442071234567",
        caller_id="+442079876543",
    )

    assert session_id == "session-123"


async def test_call_history(hass: HomeAssistant, aioclient_mock) -> None:
    """History returns a bounded normalized list of calls and recordings."""
    aioclient_mock.get(
        f"{API_BASE_URL}/history",
        json={
            "items": [
                {
                    "id": "history-1",
                    "type": "CALL",
                    "callId": "call-123",
                    "source": "+442071234567",
                    "target": "+442079876543",
                    "direction": "INCOMING",
                    "callStatus": "SUCCESS",
                    "duration": 42,
                    "recordings": [
                        {"id": "recording-1", "url": "https://example.invalid/r.mp3"}
                    ],
                    "ignored": "not exposed",
                }
            ],
            "totalCount": 1,
        },
    )
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    calls = await client.async_get_call_history(10)

    assert calls[0]["callId"] == "call-123"
    assert calls[0]["recordings"][0]["id"] == "recording-1"
    assert "ignored" not in calls[0]


async def test_non_json_success_response(hass: HomeAssistant, aioclient_mock) -> None:
    """Successful non-JSON responses are tolerated for no-payload API calls."""
    aioclient_mock.get(f"{API_BASE_URL}/account", text="ok")
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    await client.async_validate_credentials()


async def test_click_to_call_without_session_id(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A successful click-to-call response without a session ID returns None."""
    aioclient_mock.post(f"{API_BASE_URL}/sessions/calls", json={})
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    session_id = await client.async_click_to_call(
        from_endpoint="e14",
        to_number="+442071234567",
        device_id="e14",
    )

    assert session_id is None


async def test_unexpected_history_response(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Malformed history payloads are surfaced as API errors."""
    aioclient_mock.get(f"{API_BASE_URL}/history", json={"unexpected": []})
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    with pytest.raises(SipgateApiError):
        await client.async_get_call_history(10)
