"""Tests for sipgate helper functions."""

from __future__ import annotations

import pytest

from custom_components.sipgate_ha.helpers import (
    InvalidPublicUrl,
    describe_number,
    digits_key,
    normalize_public_url,
    parse_contacts,
    to_e164,
)


def test_normalize_public_url() -> None:
    """Public URLs are normalized and validated."""
    assert normalize_public_url(" https://ha.example.com/ ") == "https://ha.example.com"
    assert (
        normalize_public_url("https://example.com/homeassistant/")
        == "https://example.com/homeassistant"
    )

    with pytest.raises(InvalidPublicUrl):
        normalize_public_url("ha.example.com")
    with pytest.raises(InvalidPublicUrl):
        normalize_public_url("https://ha.example.com/?token=secret")


def test_number_helpers() -> None:
    """Numbers normalize and match across common UK formats."""
    assert to_e164("442071234567") == "+442071234567"
    assert to_e164("+442071234567") == "+442071234567"
    assert to_e164("anonymous") is None
    assert to_e164(None) is None

    assert digits_key("+442071234567", 9) == digits_key("02071234567", 9)


def test_contacts_and_description() -> None:
    """Contacts parse and produce friendly caller descriptions."""
    contacts = parse_contacts("# family\n+442071234567=Mum\n02089998888=Dentist\n", 9)

    number, name, display = describe_number("442071234567", contacts, 9)
    assert number == "+442071234567"
    assert name == "Mum"
    assert display == "Mum (+442071234567)"

    number, name, display = describe_number("anonymous", contacts, 9)
    assert number is None
    assert name is None
    assert display == "Withheld number"

    with pytest.raises(ValueError):
        parse_contacts("not-a-contact", 9)
