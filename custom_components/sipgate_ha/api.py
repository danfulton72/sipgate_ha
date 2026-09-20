"""Minimal async client for the sipgate REST API."""

from __future__ import annotations

from http import HTTPStatus
from urllib.parse import quote

from aiohttp import BasicAuth, ClientError, ClientSession

from .const import API_BASE_URL


class SipgateError(Exception):
    """Base exception for sipgate API failures."""


class SipgateAuthenticationError(SipgateError):
    """Raised when sipgate rejects the configured credentials."""


class SipgateConnectionError(SipgateError):
    """Raised when sipgate cannot be reached."""


class SipgateApiError(SipgateError):
    """Raised for an unexpected sipgate API response."""

    def __init__(self, status: int, message: str) -> None:
        """Initialize the API error."""
        super().__init__(f"sipgate API returned HTTP {status}: {message}")
        self.status = status


class SipgateClient:
    """Small client containing only the API calls the integration needs."""

    def __init__(self, session: ClientSession, token_id: str, token: str) -> None:
        """Initialize the client."""
        self._session = session
        self._auth = BasicAuth(token_id, token)

    async def _request(self, method: str, path: str) -> None:
        """Perform a sipgate API request and translate common failures."""
        try:
            async with self._session.request(
                method,
                f"{API_BASE_URL}{path}",
                auth=self._auth,
                headers={"Accept": "application/json"},
            ) as response:
                if response.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
                    raise SipgateAuthenticationError

                if response.status >= HTTPStatus.BAD_REQUEST:
                    body = (await response.text())[:200]
                    raise SipgateApiError(response.status, body)
        except SipgateError:
            raise
        except (ClientError, TimeoutError) as err:
            raise SipgateConnectionError from err

    async def async_validate_credentials(self) -> None:
        """Validate credentials against the running-calls endpoint."""
        await self._request("GET", "/calls")

    async def async_hang_up(self, call_id: str) -> None:
        """Terminate a running call."""
        await self._request("DELETE", f"/calls/{quote(call_id, safe='')}")
