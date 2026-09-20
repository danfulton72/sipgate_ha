"""Push-driven call state for sipgate.io."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import callback

Listener = Callable[[], None]


class SipgateCallState:
    """Track active and most recent calls from sipgate push events."""

    def __init__(self) -> None:
        """Initialize call state."""
        self.active_calls: dict[str, dict[str, Any]] = {}
        self.last_caller: dict[str, Any] | None = None
        self.last_call: dict[str, Any] | None = None
        self._listeners: set[Listener] = set()

    @callback
    def async_add_listener(self, listener: Listener) -> Callable[[], None]:
        """Subscribe to state changes."""
        self._listeners.add(listener)

        @callback
        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    @callback
    def started(self, data: dict[str, Any]) -> None:
        """Mark a call as ringing/starting."""
        call_id = str(data.get("call_id") or "")
        if not call_id:
            return

        call = {key: value for key, value in data.items() if value is not None}
        call.update(
            {
                "call_id": call_id,
                "status": "ringing",
                "started_at": datetime.now(UTC).isoformat(),
                "recording": False,
            }
        )
        self.active_calls[call_id] = call

        if call.get("direction") == "in":
            self.last_caller = dict(call)

        self._notify()

    @callback
    def answered(self, data: dict[str, Any]) -> None:
        """Mark a call as answered."""
        call_id = str(data.get("call_id") or "")
        if not call_id:
            return

        call = self.active_calls.setdefault(
            call_id,
            {
                "call_id": call_id,
                "started_at": datetime.now(UTC).isoformat(),
                "recording": False,
            },
        )
        self._merge(call, data)
        call["status"] = "answered"
        call["answered_at"] = datetime.now(UTC).isoformat()
        self._notify()

    @callback
    def ended(self, data: dict[str, Any]) -> None:
        """Mark a call as ended and retain it as the last call."""
        call_id = str(data.get("call_id") or "")
        if not call_id:
            return

        call = self.active_calls.pop(
            call_id,
            {
                "call_id": call_id,
                "started_at": datetime.now(UTC).isoformat(),
                "recording": False,
            },
        )
        self._merge(call, data)
        call["status"] = "ended"
        call["ended_at"] = datetime.now(UTC).isoformat()
        call["recording"] = False
        self.last_call = call
        self._notify()

    @callback
    def set_recording(self, call_id: str, recording: bool) -> None:
        """Update recording state for an active call."""
        if call := self.active_calls.get(call_id):
            call["recording"] = recording
            self._notify()

    @property
    def current_call(self) -> dict[str, Any] | None:
        """Return the most recently started active call."""
        if not self.active_calls:
            return None
        return max(
            self.active_calls.values(),
            key=lambda call: str(call.get("started_at", "")),
        )

    @property
    def state(self) -> str:
        """Return the overall call state."""
        current = self.current_call
        if current is None:
            return "idle"
        return str(current.get("status", "ringing"))

    @staticmethod
    def _merge(call: dict[str, Any], data: dict[str, Any]) -> None:
        """Merge non-empty event values without erasing earlier webhook data."""
        for key, value in data.items():
            if value is not None and value != "":
                call[key] = value

    @callback
    def _notify(self) -> None:
        """Notify subscribed entities."""
        for listener in tuple(self._listeners):
            listener()
