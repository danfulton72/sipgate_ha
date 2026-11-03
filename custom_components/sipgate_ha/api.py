"""Minimal async client for the sipgate REST API."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, encode_basic_auth

from .const import API_BASE_URL

if TYPE_CHECKING:
    from .api_usage import SipgateApiUsage


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

    def __init__(
        self,
        session: ClientSession,
        token_id: str,
        token: str,
        *,
        usage: SipgateApiUsage | None = None,
    ) -> None:
        """Initialize the client."""
        if not token_id or ":" in token_id:
            raise SipgateCredentialFormatError("token_id")
        if not token:
            raise SipgateCredentialFormatError("token")

        self._session = session
        self._authorization = encode_basic_auth(token_id, token)
        self._usage = usage

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Perform a sipgate API request and translate common failures."""
        if self._usage is not None:
            self._usage.record_request()

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
                except json.JSONDecodeError, UnicodeDecodeError:
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
        """Start a classic click-to-call session and return its session ID."""
        response = await self._request(
            "POST",
            "/sessions/calls",
            json_data=_click_to_call_body(
                from_endpoint, to_number, device_id, caller_id
            ),
        )
        return _response_id(response, "sessionId")

    async def async_neo_click_to_call(
        self,
        *,
        from_endpoint: str,
        to_number: str,
        device_id: str | None = None,
        caller_id: str | None = None,
        channel_id: str | None = None,
    ) -> str | None:
        """Start a sipgate Neo click-to-dial call and return its call ID.

        sipgate Neo replaces POST /sessions/calls with POST /calls. channelId is
        optional and defaults to the device's default channel.
        """
        data = _click_to_call_body(from_endpoint, to_number, device_id, caller_id)
        if channel_id:
            data["channelId"] = channel_id
        response = await self._request("POST", "/calls", json_data=data)
        return _response_id(response, "callId", "sessionId", "id")

    async def async_send_sms(
        self,
        *,
        sms_id: str,
        recipient: str,
        message: str,
    ) -> str | None:
        """Send an SMS and return its session ID when sipgate supplies one."""
        response = await self._request(
            "POST",
            "/sessions/sms",
            json_data={
                "smsId": sms_id,
                "recipient": recipient,
                "message": message,
            },
        )
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

    async def async_get_channels(self) -> list[dict[str, str]]:
        """Return the account's sipgate Neo channels as id/name pairs."""
        response = await self._request("GET", "/channels")
        items = _extract_items(response, "items", "channels", "data")
        if items is None:
            raise SipgateApiError(HTTPStatus.OK, "Unexpected channels response")

        channels: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            channel_id = item.get("id") or item.get("channelId")
            if not channel_id:
                continue
            name = item.get("alias") or item.get("name") or channel_id
            channels.append({"id": str(channel_id), "name": str(name)})
        return channels

    async def async_get_channel_events(
        self, channel_id: str, limit: int
    ) -> list[dict[str, Any]]:
        """Return recent call events for one sipgate Neo channel."""
        response = await self._request(
            "GET",
            f"/channels/{quote(channel_id, safe='')}/events",
            params={"limit": limit},
        )
        items = _extract_items(response, "items", "events", "data")
        if items is None:
            raise SipgateApiError(HTTPStatus.OK, "Unexpected channel events response")

        events: list[dict[str, Any]] = []
        for item in items[:limit]:
            if isinstance(item, dict):
                event = _normalize_channel_event(item)
                event.setdefault("channelId", channel_id)
                events.append(event)
        return events


def _click_to_call_body(
    from_endpoint: str,
    to_number: str,
    device_id: str | None,
    caller_id: str | None,
) -> dict[str, Any]:
    """Build the shared click-to-call request body."""
    data: dict[str, Any] = {"caller": from_endpoint, "callee": to_number}
    if device_id:
        data["deviceId"] = device_id
    if caller_id:
        data["callerId"] = caller_id
    return data


def _response_id(response: Any, *keys: str) -> str | None:
    """Return the first present identifier from a JSON response."""
    if isinstance(response, dict):
        for key in keys:
            if value := response.get(key):
                return str(value)
    return None


def _extract_items(response: Any, *keys: str) -> list[Any] | None:
    """Return a list payload, either bare or wrapped in one of the given keys."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for key in keys:
            if isinstance(response.get(key), list):
                return response[key]
    return None


# sipgate does not publish the Neo channel-event schema outside its interactive
# Swagger UI, so keep the classic history fields plus the likely Neo equivalents.
_CHANNEL_EVENT_FIELDS = (
    "id",
    "callId",
    "channelId",
    "type",
    "source",
    "target",
    "from",
    "to",
    "caller",
    "callee",
    "sourceAlias",
    "targetAlias",
    "direction",
    "incoming",
    "status",
    "callStatus",
    "result",
    "answered",
    "created",
    "lastModified",
    "timestamp",
    "startTime",
    "endTime",
    "start",
    "end",
    "duration",
    "recordings",
)

_EVENT_TIME_FIELDS = ("created", "timestamp", "startTime", "start", "lastModified")


def _normalize_channel_event(item: dict[str, Any]) -> dict[str, Any]:
    """Keep useful channel-event fields and recordings."""
    event = {key: item[key] for key in _CHANNEL_EVENT_FIELDS if key in item}
    event.setdefault("recordings", [])
    return event


def event_sort_key(event: dict[str, Any]) -> str:
    """Return a sortable timestamp for a normalized call event."""
    for key in _EVENT_TIME_FIELDS:
        if value := event.get(key):
            return str(value)
    return ""


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
