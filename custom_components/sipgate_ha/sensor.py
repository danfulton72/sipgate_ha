"""Sensors for sipgate.io."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SipgateRuntimeData
from .const import DOMAIN, NAME
from .coordinator import SipgateHistoryCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sipgate sensors."""
    runtime = entry.runtime_data
    if not isinstance(runtime, SipgateRuntimeData):
        return

    async_add_entities(
        [
            SipgateCallStateSensor(entry, runtime),
            SipgateLastCallerSensor(entry, runtime),
            SipgateLastCallSensor(entry, runtime),
            SipgateRecentCallsSensor(entry, runtime.history_coordinator),
            SipgateApiRequestsTodaySensor(entry, runtime),
            SipgateApiRequestsLifetimeSensor(entry, runtime),
        ]
    )
    hass.async_create_task(runtime.history_coordinator.async_request_refresh())


class SipgatePushSensor(SensorEntity):
    """Base class for push-driven sipgate sensors."""

    _attr_has_entity_name = True

    def __init__(
        self, entry: ConfigEntry, runtime: SipgateRuntimeData, key: str
    ) -> None:
        """Initialize a push sensor."""
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Subscribe to push-state changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._runtime.call_state.async_add_listener(self.async_write_ha_state)
        )


class SipgateCallStateSensor(SipgatePushSensor):
    """Current overall sipgate call state."""

    _attr_translation_key = "call_state"

    def __init__(self, entry: ConfigEntry, runtime: SipgateRuntimeData) -> None:
        """Initialize the sensor."""
        super().__init__(entry, runtime, "call_state")

    @property
    def native_value(self) -> str:
        """Return idle, ringing, or answered."""
        return self._runtime.call_state.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return current active call details."""
        return {
            "active_calls": list(self._runtime.call_state.active_calls.values()),
            "active_call_count": len(self._runtime.call_state.active_calls),
        }


class SipgateLastCallerSensor(SipgatePushSensor):
    """Most recent incoming caller."""

    _attr_translation_key = "last_caller"

    def __init__(self, entry: ConfigEntry, runtime: SipgateRuntimeData) -> None:
        """Initialize the sensor."""
        super().__init__(entry, runtime, "last_caller")

    @property
    def native_value(self) -> str | None:
        """Return the friendly caller display."""
        caller = self._runtime.call_state.last_caller
        return str(caller.get("display")) if caller and caller.get("display") else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return caller metadata."""
        return dict(self._runtime.call_state.last_caller or {})


class SipgateLastCallSensor(SipgatePushSensor):
    """Most recently ended call."""

    _attr_translation_key = "last_call"

    def __init__(self, entry: ConfigEntry, runtime: SipgateRuntimeData) -> None:
        """Initialize the sensor."""
        super().__init__(entry, runtime, "last_call")

    @property
    def native_value(self) -> str | None:
        """Return the most useful final call result."""
        call = self._runtime.call_state.last_call
        if call is None:
            return None
        return str(call.get("cause") or call.get("status") or "ended")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return last-call metadata."""
        return dict(self._runtime.call_state.last_call or {})


class SipgateRecentCallsSensor(
    CoordinatorEntity[SipgateHistoryCoordinator], SensorEntity
):
    """Bounded recent sipgate call history."""

    _attr_has_entity_name = True
    _attr_translation_key = "recent_calls"

    def __init__(
        self, entry: ConfigEntry, coordinator: SipgateHistoryCoordinator
    ) -> None:
        """Initialize the history sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_recent_calls"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> int:
        """Return the number of recent calls exposed in attributes."""
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the bounded call-history list."""
        return {"calls": self.coordinator.data or []}


class SipgateApiUsageSensor(SensorEntity):
    """Base sensor for sipgate REST API request counters."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:api"
    _attr_native_unit_of_measurement = "requests"

    def __init__(
        self, entry: ConfigEntry, runtime: SipgateRuntimeData, key: str
    ) -> None:
        """Initialize the API usage sensor."""
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Subscribe to API usage changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._runtime.api_usage.async_add_listener(self.async_write_ha_state)
        )


class SipgateApiRequestsTodaySensor(SipgateApiUsageSensor):
    """REST API requests made today."""

    _attr_translation_key = "api_requests_today"

    def __init__(self, entry: ConfigEntry, runtime: SipgateRuntimeData) -> None:
        """Initialize the daily request sensor."""
        super().__init__(entry, runtime, "api_requests_today")

    @property
    def native_value(self) -> int:
        """Return today's REST API request count."""
        return self._runtime.api_usage.today


class SipgateApiRequestsLifetimeSensor(SipgateApiUsageSensor):
    """REST API requests made since tracking was enabled."""

    _attr_translation_key = "api_requests_lifetime"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, entry: ConfigEntry, runtime: SipgateRuntimeData) -> None:
        """Initialize the lifetime request sensor."""
        super().__init__(entry, runtime, "api_requests_lifetime")

    @property
    def native_value(self) -> int:
        """Return the persisted lifetime REST API request count."""
        return self._runtime.api_usage.lifetime


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return common service-device metadata."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=NAME,
        manufacturer="sipgate",
        entry_type=DeviceEntryType.SERVICE,
    )
