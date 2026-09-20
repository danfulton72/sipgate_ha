"""Tests for the minimal sipgate REST client."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.sipgate_ha.api import (
    SipgateApiError,
    SipgateAuthenticationError,
    SipgateClient,
)
from custom_components.sipgate_ha.const import API_BASE_URL


async def test_validate_credentials(hass: HomeAssistant, aioclient_mock) -> None:
    """A successful calls request validates the PAT."""
    aioclient_mock.get(f"{API_BASE_URL}/calls", json=[])
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    await client.async_validate_credentials()


async def test_authentication_error(hass: HomeAssistant, aioclient_mock) -> None:
    """401 and 403 responses are authentication errors."""
    aioclient_mock.get(f"{API_BASE_URL}/calls", status=403)
    client = SipgateClient(async_get_clientsession(hass), "token-id", "secret")

    with pytest.raises(SipgateAuthenticationError):
        await client.async_validate_credentials()


async def test_api_error(hass: HomeAssistant, aioclient_mock) -> None:
    """Other HTTP failures retain their status and a bounded response body."""
    aioclient_mock.get(f"{API_BASE_URL}/calls", status=500, text="server error")
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
