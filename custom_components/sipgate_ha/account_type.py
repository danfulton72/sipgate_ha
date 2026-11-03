"""Detect whether the sipgate account runs on Classic or sipgate Neo."""

from __future__ import annotations

import logging
import time
from typing import Any

from .api import (
    SipgateApiError,
    SipgateAuthorizationError,
    SipgateClient,
    SipgateConnectionError,
)
from .const import (
    ACCOUNT_TYPE_AUTO,
    ACCOUNT_TYPE_CLASSIC,
    ACCOUNT_TYPE_NEO,
    CLASSIC_RECHECK_SECONDS,
    MAX_AUTO_CHANNELS,
)

_LOGGER = logging.getLogger(__name__)


def parse_channel_ids(value: str | None) -> list[str]:
    """Split a comma/whitespace separated list of channel IDs."""
    if not value:
        return []
    ids: list[str] = []
    for part in value.replace(",", " ").split():
        if part not in ids:
            ids.append(part)
    return ids


class SipgateAccountType:
    """Resolve and cache the account type and the channels to read events from.

    Personal Access Tokens carry no ``featureScope`` claim, so in automatic mode
    the account counts as sipgate Neo when ``GET /channels`` returns channels.
    A Classic result is re-checked periodically so the in-place upgrade to Neo
    is picked up without restarting Home Assistant.
    """

    def __init__(
        self,
        client: SipgateClient,
        configured: str,
        channel_ids: list[str],
    ) -> None:
        """Initialize the resolver."""
        self._client = client
        self.configured = configured
        self.configured_channel_ids = channel_ids
        self.detected: str | None = None
        self.detection_detail: str | None = None
        self._detected_at: float | None = None
        self._discovered_channels: list[dict[str, str]] = []

    async def async_is_neo(self) -> bool:
        """Return True when Neo endpoints should be used."""
        if self.configured == ACCOUNT_TYPE_NEO:
            return True
        if self.configured == ACCOUNT_TYPE_CLASSIC:
            return False

        if self.detected == ACCOUNT_TYPE_NEO:
            return True
        if (
            self.detected == ACCOUNT_TYPE_CLASSIC
            and self._detected_at is not None
            and time.monotonic() - self._detected_at < CLASSIC_RECHECK_SECONDS
        ):
            return False

        await self._async_detect()
        return self.detected == ACCOUNT_TYPE_NEO

    async def _async_detect(self) -> None:
        """Probe the channels endpoint to classify the account."""
        try:
            channels = await self._client.async_get_channels()
        except SipgateConnectionError:
            # Keep the previous answer (Classic when unknown) and retry next time.
            _LOGGER.debug("Could not reach sipgate to detect the account type")
            return
        except SipgateAuthorizationError:
            self._set_detected(
                ACCOUNT_TYPE_CLASSIC,
                "GET /channels returned 403; the token may lack channel access",
            )
            return
        except SipgateApiError as err:
            self._set_detected(
                ACCOUNT_TYPE_CLASSIC, f"GET /channels returned HTTP {err.status}"
            )
            return

        if channels:
            self._discovered_channels = channels
            self._set_detected(
                ACCOUNT_TYPE_NEO, f"GET /channels returned {len(channels)} channel(s)"
            )
        else:
            self._set_detected(ACCOUNT_TYPE_CLASSIC, "GET /channels returned none")

    def _set_detected(self, account_type: str, detail: str) -> None:
        """Record a detection result and log changes."""
        if account_type != self.detected:
            _LOGGER.info("sipgate account detected as %s (%s)", account_type, detail)
        self.detected = account_type
        self.detection_detail = detail
        self._detected_at = time.monotonic()

    async def async_channel_ids(self) -> list[str]:
        """Return the channel IDs whose events make up the call history."""
        if self.configured_channel_ids:
            return self.configured_channel_ids
        if not self._discovered_channels:
            self._discovered_channels = await self._client.async_get_channels()
        return [
            channel["id"] for channel in self._discovered_channels[:MAX_AUTO_CHANNELS]
        ]

    def as_diagnostics(self) -> dict[str, Any]:
        """Return non-sensitive state for diagnostics."""
        return {
            "configured": self.configured,
            "detected": self.detected,
            "detection_detail": self.detection_detail,
            "configured_channel_ids": self.configured_channel_ids,
            "discovered_channels": self._discovered_channels,
            "auto_mode": self.configured == ACCOUNT_TYPE_AUTO,
        }
