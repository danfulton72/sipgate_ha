"""Binary sensors for sipgate.io."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SipgateRuntimeData
from .const import DOMAIN, NAME


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sipgate binary sensors."""
    del hass
    runtime = entry.runtime_data
    if not isinstance(runtime, SipgateRuntimeData):
        return
    async_add_entities([SipgateCallActiveBinarySensor(entry, runtime)])


class SipgateCallActiveBinarySensor(BinarySensorEntity):
    """Whether sipgate currently has one or more tracked active calls."""

    _attr_has_entity_name = True
    _attr_translation_key = "call_active"

    def __init__(self, entry: ConfigEntry, runtime: SipgateRuntimeData) -> None:
        """Initialize the entity."""
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_call_active"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="sipgate",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to push-state changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._runtime.call_state.async_add_listener(self.async_write_ha_state)
        )

    @property
    def is_on(self) -> bool:
        """Return whether any tracked call is active."""
        return bool(self._runtime.call_state.active_calls)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose useful current-call details."""
        return {
            "active_call_count": len(self._runtime.call_state.active_calls),
            "current_call": self._runtime.call_state.current_call,
        }
