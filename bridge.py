#!/usr/bin/env python3
"""
sipgate.io push API -> Home Assistant bridge.

Receives sipgate.io push-API webhooks, resolves the caller against a local
contact list, and fires events into Home Assistant. Home Assistant owns all
notification policy; this service only translates protocols.

The newCall handler is on the critical path of call setup -- sipgate waits for
our XML before the phone rings -- so it does the minimum possible work
synchronously and dispatches the Home Assistant call in the background.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import pathlib
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("sipgate-bridge")

HA_URL = os.environ["HA_URL"].rstrip("/")
HA_TOKEN = os.environ["HA_TOKEN"]
WEBHOOK_TOKEN = os.environ["WEBHOOK_TOKEN"]
# Must be the full externally reachable prefix INCLUDING the webhook token,
# e.g. https://calls.example.com/8f3a1c...  -- sipgate needs absolute URLs.
PUBLIC_BASE = os.environ["PUBLIC_BASE"].rstrip("/")
CONTACTS_PATH = pathlib.Path(os.getenv("CONTACTS_PATH", "/data/contacts.json"))

XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>'

_contacts: dict[str, str] = {}
_contacts_mtime: float | None = None
_http: httpx.AsyncClient | None = None


# --------------------------------------------------------------------------
# Number handling
# --------------------------------------------------------------------------

def digits_key(number: str) -> str:
    """
    Index numbers by their last 9 significant digits.

    This makes +442071234567, 02071234567 and 00442071234567 all collide onto
    the same key, which saves you from normalising your contacts perfectly.
    Drop to 7 if you have a lot of short national numbers; raise it if you get
    false positives.
    """
    d = re.sub(r"\D", "", number)
    return d[-9:] if len(d) >= 9 else d


def to_e164(raw: str | None) -> str | None:
    """sipgate sends '492111234567' or the literal 'anonymous'."""
    if not raw or raw.lower() == "anonymous":
        return None
    return raw if raw.startswith("+") else "+" + raw


def load_contacts() -> None:
    """Reload contacts.json if it changed on disk. Cheap enough to call often."""
    global _contacts, _contacts_mtime
    try:
        mtime = CONTACTS_PATH.stat().st_mtime
    except OSError:
        if _contacts_mtime is not None:
            log.warning("contacts file %s disappeared, keeping cache", CONTACTS_PATH)
        return
    if mtime == _contacts_mtime:
        return
    try:
        raw = json.loads(CONTACTS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.exception("could not parse %s, keeping previous contacts", CONTACTS_PATH)
        return
    _contacts = {digits_key(k): v for k, v in raw.items()}
    _contacts_mtime = mtime
    log.info("loaded %d contacts", len(_contacts))


def describe(raw: str | None) -> tuple[str | None, str | None, str]:
    """Return (e164, name_or_None, display_string)."""
    number = to_e164(raw)
    if number is None:
        return None, None, "Withheld number"
    load_contacts()
    name = _contacts.get(digits_key(number))
    return number, name, f"{name} ({number})" if name else number


# --------------------------------------------------------------------------
# Home Assistant
# --------------------------------------------------------------------------

async def fire(event_type: str, data: dict) -> None:
    """Fire an event on the Home Assistant bus. Never raises."""
    if _http is None:
        return
    try:
        resp = await _http.post(
            f"{HA_URL}/api/events/{event_type}",
            headers={"Authorization": f"Bearer {HA_TOKEN}"},
            json=data,
        )
        resp.raise_for_status()
        log.info("fired %s %s", event_type, data.get("call_id"))
    except Exception:
        log.exception("failed to fire %s", event_type)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _http
    _http = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))
    load_contacts()
    log.info("bridge up, advertising %s to sipgate", PUBLIC_BASE)
    yield
    await _http.aclose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def check(token: str) -> None:
    """
    sipgate.io does not sign its webhooks, so the only thing standing between
    the internet and your call log is an unguessable path segment. Keep it long
    and terminate TLS in front of this service.
    """
    if not hmac.compare_digest(token, WEBHOOK_TOKEN):
        raise HTTPException(status_code=404)


# --------------------------------------------------------------------------
# Webhook endpoints
# --------------------------------------------------------------------------

@app.post("/{token}/newcall")
async def new_call(token: str, request: Request) -> Response:
    check(token)
    form = await request.form()

    call_id = form.get("callId", "")
    direction = form.get("direction", "")
    number, name, display = describe(form.get("from"))

    if direction == "in":
        asyncio.create_task(fire("sipgate_call_started", {
            "call_id": call_id,
            "orig_call_id": form.get("origCallId"),
            "direction": direction,
            "from": number,
            "to": to_e164(form.get("to")),
            "name": name,
            "display": display,
            "known": name is not None,
            "anonymous": number is None,
            # Always an array, even for a single user -- group calls ring several.
            "users": form.getlist("user[]"),
            "user_ids": form.getlist("userId[]"),
            # Set when the call was diverted before it reached sipgate.io.
            "diversion": to_e164(form.get("diversion")),
        }))

    # No action verb: the call proceeds exactly as it would have. We only
    # subscribe to the follow-up events so we can dismiss the notification.
    body = (
        f'{XML_DECL}<Response onAnswer="{PUBLIC_BASE}/answer" '
        f'onHangup="{PUBLIC_BASE}/hangup"/>'
    )
    return Response(content=body, media_type="application/xml")


@app.post("/{token}/answer")
async def on_answer(token: str, request: Request) -> Response:
    check(token)
    form = await request.form()
    asyncio.create_task(fire("sipgate_call_answered", {
        "call_id": form.get("callId", ""),
        "answered_by": form.get("user"),
        "answering_number": to_e164(form.get("answeringNumber")),
        "direction": form.get("direction"),
    }))
    return Response(status_code=204)


@app.post("/{token}/hangup")
async def on_hangup(token: str, request: Request) -> Response:
    check(token)
    form = await request.form()
    # cause is one of: normalClearing, busy, cancel, noAnswer, congestion,
    # notFound, forwarded
    asyncio.create_task(fire("sipgate_call_ended", {
        "call_id": form.get("callId", ""),
        "cause": form.get("cause"),
        "direction": form.get("direction"),
        "from": to_e164(form.get("from")),
        "answering_number": to_e164(form.get("answeringNumber")),
    }))
    return Response(status_code=204)


@app.get("/healthz")
async def healthz() -> dict:
    load_contacts()
    return {"ok": True, "contacts": len(_contacts)}
