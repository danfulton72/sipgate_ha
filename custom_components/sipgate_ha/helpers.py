"""Helpers for number normalization, contacts, and webhook URLs."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from homeassistant.components.webhook import async_generate_path


class InvalidPublicUrl(ValueError):
    """Raised when the configured public Home Assistant URL is invalid."""


def normalize_public_url(value: str) -> str:
    """Validate and normalize a public Home Assistant base URL."""
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InvalidPublicUrl
    if parsed.query or parsed.fragment:
        raise InvalidPublicUrl
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def build_webhook_url(public_url: str, webhook_id: str) -> str:
    """Return the externally reachable Home Assistant webhook URL."""
    return f"{public_url}{async_generate_path(webhook_id)}"


def digits_key(number: str, significant_digits: int) -> str:
    """Return a comparison key based on the final significant digits."""
    digits = re.sub(r"\D", "", number)
    if len(digits) <= significant_digits:
        return digits
    return digits[-significant_digits:]


def to_e164(raw: str | None) -> str | None:
    """Normalize sipgate's number representation to a leading plus."""
    if not raw or raw.lower() == "anonymous":
        return None
    return raw if raw.startswith("+") else f"+{raw}"


def parse_contacts(value: str, significant_digits: int) -> dict[str, str]:
    """Parse `number=Name` lines into normalized lookup keys."""
    contacts: dict[str, str] = {}
    for line_number, raw_line in enumerate(value.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid contact on line {line_number}")
        number, name = (part.strip() for part in line.split("=", 1))
        if not number or not name or not re.search(r"\d", number):
            raise ValueError(f"Invalid contact on line {line_number}")
        contacts[digits_key(number, significant_digits)] = name
    return contacts


def describe_number(
    raw: str | None, contacts: dict[str, str], significant_digits: int
) -> tuple[str | None, str | None, str]:
    """Return normalized number, optional contact name, and display text."""
    number = to_e164(raw)
    if number is None:
        return None, None, "Withheld number"
    name = contacts.get(digits_key(number, significant_digits))
    if name:
        return number, name, f"{name} ({number})"
    return number, None, number
