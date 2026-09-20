"""Persistent sipgate REST API request counters."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_STORAGE_VERSION = 1
_STORAGE_KEY = f"{DOMAIN}.api_usage"


class SipgateApiUsage:
    """Track REST API requests made by the loaded integration."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the counter."""
        self._hass = hass
        self._store = Store[dict[str, Any]](
            hass,
            _STORAGE_VERSION,
            _STORAGE_KEY,
        )
        self._save_lock = asyncio.Lock()
        self._listeners: set[Callable[[], None]] = set()
        self._date = self._today_key()
        self._today = 0
        self._lifetime = 0
        self._unsub_midnight: Callable[[], None] | None = None

    async def async_load(self) -> None:
        """Load persisted counters."""
        data = await self._store.async_load() or {}
        self._lifetime = max(0, int(data.get("lifetime", 0)))
        stored_date = str(data.get("date", ""))
        today = self._today_key()
        self._date = today
        self._today = max(0, int(data.get("today", 0))) if stored_date == today else 0

    @callback
    def start(self) -> None:
        """Start the local-midnight reset timer."""
        if self._unsub_midnight is None:
            self._unsub_midnight = async_track_time_change(
                self._hass,
                self._handle_midnight,
                hour=0,
                minute=0,
                second=0,
            )

    @callback
    def stop(self) -> None:
        """Stop the local-midnight reset timer."""
        if self._unsub_midnight is not None:
            self._unsub_midnight()
            self._unsub_midnight = None

    @callback
    def record_request(self) -> None:
        """Record one attempted REST API request."""
        self._rollover_if_needed()
        self._today += 1
        self._lifetime += 1
        self._notify_listeners()
        self._hass.async_create_task(self._async_save())

    @property
    def today(self) -> int:
        """Return requests made today."""
        if self._date != self._today_key():
            return 0
        return self._today

    @property
    def lifetime(self) -> int:
        """Return requests made since tracking was introduced."""
        return self._lifetime

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a state listener."""
        self._listeners.add(listener)

        @callback
        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    @callback
    def _handle_midnight(self, _now: Any) -> None:
        """Reset the daily counter at local midnight."""
        self._date = self._today_key()
        self._today = 0
        self._notify_listeners()
        self._hass.async_create_task(self._async_save())

    @callback
    def _rollover_if_needed(self) -> None:
        """Reset a stale daily count before recording a request."""
        today = self._today_key()
        if self._date == today:
            return
        self._date = today
        self._today = 0

    @callback
    def _notify_listeners(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    async def _async_save(self) -> None:
        """Persist the latest counter values in request order."""
        async with self._save_lock:
            await self._store.async_save(
                {
                    "date": self._date,
                    "today": self._today,
                    "lifetime": self._lifetime,
                }
            )

    @staticmethod
    def _today_key() -> str:
        """Return the current Home Assistant local date."""
        return dt_util.now().date().isoformat()
