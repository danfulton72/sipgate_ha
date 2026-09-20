"""Tests for the sipgate.io config flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_TOKEN, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.sipgate_ha.const import (
    API_BASE_URL,
    CONF_CONTACTS,
    CONF_INCLUDE_OUTGOING,
    CONF_PUBLIC_URL,
    CONF_SIGNIFICANT_DIGITS,
    CONF_TOKEN_ID,
    DOMAIN,
)


async def test_user_flow(hass: HomeAssistant, aioclient_mock) -> None:
    """A valid PAT leads to a webhook confirmation and config entry."""
    aioclient_mock.get(f"{API_BASE_URL}/authorization/userinfo", json={"sub": "w0"})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TOKEN_ID: "token-test-0",
            CONF_TOKEN: "secret-token",
            CONF_PUBLIC_URL: "https://ha.example.com/",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "webhook"
    webhook_url = result["description_placeholders"]["webhook_url"]
    assert webhook_url.startswith("https://ha.example.com/api/webhook/")

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "sipgate.io"
    assert result["data"][CONF_PUBLIC_URL] == "https://ha.example.com"
    assert result["data"][CONF_TOKEN] == "secret-token"
    assert result["data"][CONF_WEBHOOK_ID]


async def test_invalid_auth(hass: HomeAssistant, aioclient_mock) -> None:
    """Invalid PAT credentials are reported in the setup form."""
    aioclient_mock.get(f"{API_BASE_URL}/authorization/userinfo", status=401)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TOKEN_ID: "bad-token-id",
            CONF_TOKEN: "bad-token",
            CONF_PUBLIC_URL: "https://ha.example.com",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_invalid_public_url(hass: HomeAssistant) -> None:
    """A non-URL public address is rejected before contacting sipgate."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TOKEN_ID: "token-test-0",
            CONF_TOKEN: "secret-token",
            CONF_PUBLIC_URL: "not-a-url",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PUBLIC_URL: "invalid_url"}


async def test_options_flow(hass: HomeAssistant, mock_config_entry) -> None:
    """Caller matching and outgoing-event behaviour are configurable."""
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_INCLUDE_OUTGOING: True,
            CONF_SIGNIFICANT_DIGITS: 10,
            CONF_CONTACTS: "+442071234567=Mum",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_INCLUDE_OUTGOING] is True
    assert result["data"][CONF_SIGNIFICANT_DIGITS] == 10


async def test_options_reject_bad_contacts(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Malformed contact mappings are rejected."""
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_INCLUDE_OUTGOING: False,
            CONF_SIGNIFICANT_DIGITS: 9,
            CONF_CONTACTS: "broken mapping",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_CONTACTS: "invalid_contacts"}


async def test_duplicate_setup_aborts(hass: HomeAssistant, mock_config_entry) -> None:
    """Only one sipgate.io account can be configured."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_unexpected_api_error(hass: HomeAssistant, aioclient_mock) -> None:
    """Unexpected sipgate HTTP failures stay on the setup form."""
    aioclient_mock.get(
        f"{API_BASE_URL}/authorization/userinfo", status=500, text="server error"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TOKEN_ID: "token-test-0",
            CONF_TOKEN: "secret-token",
            CONF_PUBLIC_URL: "https://ha.example.com",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_reauth_flow(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """Valid replacement credentials complete the reauthentication flow."""
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert not result["errors"]

    aioclient_mock.get(f"{API_BASE_URL}/authorization/userinfo", json={"sub": "w0"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TOKEN_ID: "token-reauth-0",
            CONF_TOKEN: "reauth-secret",
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_TOKEN_ID] == "token-reauth-0"
    assert mock_config_entry.data[CONF_TOKEN] == "reauth-secret"


async def test_reconfigure_flow(
    hass: HomeAssistant, mock_config_entry, aioclient_mock
) -> None:
    """Reconfigure updates credentials and the public URL without rotating the hook."""
    aioclient_mock.get(f"{API_BASE_URL}/authorization/userinfo", json={"sub": "w0"})
    original_webhook_id = mock_config_entry.data[CONF_WEBHOOK_ID]

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TOKEN_ID: "token-new-0",
            CONF_TOKEN: "new-secret",
            CONF_PUBLIC_URL: "https://new-ha.example.com/",
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_TOKEN_ID] == "token-new-0"
    assert mock_config_entry.data[CONF_TOKEN] == "new-secret"
    assert mock_config_entry.data[CONF_PUBLIC_URL] == "https://new-ha.example.com"
    assert mock_config_entry.data[CONF_WEBHOOK_ID] == original_webhook_id
