"""Shared fixtures for sipgate.io tests."""

from __future__ import annotations

import pytest

from homeassistant.const import CONF_TOKEN, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sipgate_ha.const import (
    CONF_PUBLIC_URL,
    CONF_TOKEN_ID,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in tests."""
    yield


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a configured sipgate entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="sipgate.io",
        data={
            CONF_TOKEN_ID: "token-test-0",
            CONF_TOKEN: "secret-token",
            CONF_PUBLIC_URL: "https://ha.example.com",
            CONF_WEBHOOK_ID: "test-webhook-id",
        },
        options={},
    )
    entry.add_to_hass(hass)
    return entry
