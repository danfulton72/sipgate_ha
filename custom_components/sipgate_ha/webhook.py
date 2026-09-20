"""sipgate.io webhook handling."""

from __future__ import annotations

from html import escape
from http import HTTPStatus
from typing import Any

from aiohttp.web import Request, Response
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from multidict import MultiDictProxy

from .const import (
    CONF_CONTACTS,
    CONF_INCLUDE_OUTGOING,
    CONF_SIGNIFICANT_DIGITS,
    DEFAULT_INCLUDE_OUTGOING,
    DEFAULT_SIGNIFICANT_DIGITS,
    EVENT_CALL_ANSWERED,
    EVENT_CALL_ENDED,
    EVENT_CALL_STARTED,
)
from .helpers import describe_number, parse_contacts, to_e164

XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'


def _string(form: MultiDictProxy[str], key: str) -> str | None:
    """Return a form value as a string when present."""
    value = form.get(key)
    return str(value) if value is not None else None


def _base_event_data(entry: ConfigEntry, form: MultiDictProxy[str]) -> dict[str, Any]:
    """Build common event data."""
    return {
        "entry_id": entry.entry_id,
        "call_id": _string(form, "callId") or "",
        "direction": _string(form, "direction"),
        "from": to_e164(_string(form, "from")),
        "to": to_e164(_string(form, "to")),
        "diversion": to_e164(_string(form, "diversion")),
    }


async def async_handle_webhook(
    hass: HomeAssistant,
    webhook_id: str,
    request: Request,
    *,
    entry: ConfigEntry,
    webhook_url: str,
) -> Response:
    """Handle all sipgate push events on one Home Assistant webhook."""
    del webhook_id
    form = await request.post()
    event = _string(form, "event")

    if event == "newCall":
        return _handle_new_call(hass, entry, form, webhook_url)
    if event == "answer":
        _handle_answer(hass, entry, form)
        return Response(status=HTTPStatus.NO_CONTENT)
    if event == "hangup":
        _handle_hangup(hass, entry, form)
        return Response(status=HTTPStatus.NO_CONTENT)

    return Response(status=HTTPStatus.NO_CONTENT)


def _handle_new_call(
    hass: HomeAssistant,
    entry: ConfigEntry,
    form: MultiDictProxy[str],
    webhook_url: str,
) -> Response:
    """Handle a new-call event and immediately return sipgate XML."""
    direction = _string(form, "direction")
    include_outgoing = entry.options.get(
        CONF_INCLUDE_OUTGOING, DEFAULT_INCLUDE_OUTGOING
    )
    if direction == "in" or include_outgoing:
        significant_digits = entry.options.get(
            CONF_SIGNIFICANT_DIGITS, DEFAULT_SIGNIFICANT_DIGITS
        )
        contacts = parse_contacts(
            entry.options.get(CONF_CONTACTS, ""), significant_digits
        )
        number, name, display = describe_number(
            _string(form, "from"), contacts, significant_digits
        )
        data = _base_event_data(entry, form)
        data.update(
            {
                "orig_call_id": _string(form, "origCallId"),
                "xcid": _string(form, "xcid"),
                "from": number,
                "name": name,
                "display": display,
                "known": name is not None,
                "anonymous": number is None,
                "users": [str(value) for value in form.getall("user[]", [])],
                "user_ids": [str(value) for value in form.getall("userId[]", [])],
                "full_user_ids": [
                    str(value) for value in form.getall("fullUserId[]", [])
                ],
            }
        )
        hass.bus.async_fire(EVENT_CALL_STARTED, data)

    callback_url = escape(webhook_url, quote=True)
    body = (
        f'{XML_DECLARATION}<Response onAnswer="{callback_url}" '
        f'onHangup="{callback_url}"/>'
    )
    return Response(text=body, content_type="application/xml")


def _handle_answer(
    hass: HomeAssistant, entry: ConfigEntry, form: MultiDictProxy[str]
) -> None:
    """Handle an answer event."""
    data = _base_event_data(entry, form)
    data.update(
        {
            "answered_by": _string(form, "user"),
            "user_id": _string(form, "userId"),
            "full_user_id": _string(form, "fullUserId"),
            "answering_number": to_e164(_string(form, "answeringNumber")),
        }
    )
    hass.bus.async_fire(EVENT_CALL_ANSWERED, data)


def _handle_hangup(
    hass: HomeAssistant, entry: ConfigEntry, form: MultiDictProxy[str]
) -> None:
    """Handle a hangup event."""
    data = _base_event_data(entry, form)
    data.update(
        {
            "cause": _string(form, "cause"),
            "answering_number": to_e164(_string(form, "answeringNumber")),
        }
    )
    hass.bus.async_fire(EVENT_CALL_ENDED, data)
