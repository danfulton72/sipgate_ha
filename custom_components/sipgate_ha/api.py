"""Minimal async client for the sipgate REST API."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, encode_basic_auth

from .const import API_BASE_URL


class SipgateError(Exception):
    """Base exception for sipgate API failures."""


class SipgateAuthenticationError(SipgateError):
    """Raised when sipgate rejects the configured credentials."""


class SipgateConnectionError(SipgateError):
    """Raised when sipgate cannot be reached."""


class SipgateCredentialFormatError(SipgateError):
    """Raised when PAT fields cannot form valid HTTP Basic credentials."""

    def __init__(self, field: str) -> None:
        """Initialize the credential-format error."""
        super().__init__(field)
        self.field = field


class SipgateAuthorizationError(SipgateError):
    """Raised when valid credentials lack permission for an API resource."""


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
        if not token_id or ":" in token_id:
            raise SipgateCredentialFormatError("token_id")
        if not token:
            raise SipgateCredentialFormatError("token")

        self._session = session
        self._authorization = encode_basic_auth(token_id, token)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Perform a sipgate API request and translate common failures."""
        headers = {
            "Accept": "application/json",
            "Authorization": self._authorization,
        }
        if json_data is not None:
            headers["Content-Type"] = "application/json"

        try:
            async with self._session.request(
                method,
                f"{API_BASE_URL}{path}",
                headers=headers,
                json=json_data,
                params=params,
            ) as response:
                body = await response.read()

                if response.status == HTTPStatus.UNAUTHORIZED:
                    raise SipgateAuthenticationError

                if response.status == HTTPStatus.FORBIDDEN:
                    raise SipgateAuthorizationError

                if response.status >= HTTPStatus.BAD_REQUEST:
                    message = body.decode(errors="replace")[:200]
                    raise SipgateApiError(response.status, message)

                if not body:
                    return None

                try:
                    return json.loads(body)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return body.decode(errors="replace")
        except SipgateError:
            raise
        except (ClientError, TimeoutError) as err:
            raise SipgateConnectionError from err

    async def async_validate_credentials(self) -> None:
        """Validate credentials against sipgate's account endpoint."""
        await self._request("GET", "/account")

    async def async_hang_up(self, call_id: str) -> None:
        """Terminate a running call."""
        await self._request("DELETE", f"/calls/{quote(call_id, safe='')}")

    async def async_set_recording(
        self, call_id: str, *, recording: bool, announcement: bool
    ) -> None:
        """Start or stop recording an active call."""
        await self._request(
            "PUT",
            f"/calls/{quote(call_id, safe='')}/recording",
            json_data={"value": recording, "announcement": announcement},
        )

    async def async_click_to_call(
        self,
        *,
        from_endpoint: str,
        to_number: str,
        device_id: str | None = None,
        caller_id: str | None = None,
    ) -> str | None:
        """Initiate a click-to-call session and return its session ID."""
        data: dict[str, Any] = {
            "caller": from_endpoint,
            "callee": to_number,
        }
        if device_id:
            data["deviceId"] = device_id
        if caller_id:
            data["callerId"] = caller_id

        response = await self._request("POST", "/sessions/calls", json_data=data)
        if isinstance(response, dict):
            session_id = response.get("sessionId")
            return str(session_id) if session_id else None
        return None

    async def async_get_call_history(self, limit: int) -> list[dict[str, Any]]:
        """Return a bounded list of recent CALL history entries."""
        response = await self._request(
            "GET",
            "/history",
            params={"types": "CALL", "limit": limit},
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise SipgateApiError(HTTPStatus.OK, "Unexpected history response")

        calls: list[dict[str, Any]] = []
        for item in response["items"][:limit]:
            if isinstance(item, dict):
                calls.append(_normalize_history_entry(item))
        return calls


def _normalize_history_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Keep useful, stable call-history fields and recording URLs."""
    fields = (
        "id",
        "callId",
        "source",
        "target",
        "sourceAlias",
        "targetAlias",
        "type",
        "created",
        "lastModified",
        "direction",
        "incoming",
        "status",
        "callStatus",
        "duration",
        "connectionIds",
        "recordings",
    )
    return {key: item[key] for key in fields if key in item}
