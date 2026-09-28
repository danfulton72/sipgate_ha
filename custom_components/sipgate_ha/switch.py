"""Configuration switches for sipgate.io automatic recording."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import SipgateRuntimeData
from .const import DOMAIN, NAME


@dataclass(frozen=True, kw_only=True)
class SipgateRecordingSwitchDescription(SwitchEntityDescription):
    """Describe a sipgate recording configuration switch."""

    preference: str


SWITCHES = (
    SipgateRecordingSwitchDescription(
        key="record_incoming_calls",
        translation_key="record_incoming_calls",
        icon="mdi:record-rec",
        preference="record_incoming",
    ),
    SipgateRecordingSwitchDescription(
        key="announce_incoming_recording",
        translation_key="announce_incoming_recording",
        icon="mdi:bullhorn",
        preference="announce_incoming",
    ),
    SipgateRecordingSwitchDescription(
        key="record_outgoing_calls",
        translation_key="record_outgoing_calls",
        icon="mdi:record-rec",
        preference="record_outgoing",
    ),
    SipgateRecordingSwitchDescription(
        key="announce_outgoing_recording",
        translation_key="announce_outgoing_recording",
        icon="mdi:bullhorn",
        preference="announce_outgoing",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sipgate automatic-recording switches."""
    del hass
    runtime = entry.runtime_data
    if not isinstance(runtime, SipgateRuntimeData):
        return

    async_add_entities(
        SipgateRecordingSwitch(entry, runtime, description) for description in SWITCHES
    )


class SipgateRecordingSwitch(SwitchEntity, RestoreEntity):
    """A persisted automatic-recording preference."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    entity_description: SipgateRecordingSwitchDescription

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: SipgateRuntimeData,
        description: SipgateRecordingSwitchDescription,
    ) -> None:
        """Initialize the recording switch."""
        self._runtime = runtime
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="sipgate",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        """Return the current recording preference."""
        return bool(
            getattr(
                self._runtime.recording_preferences,
                self.entity_description.preference,
            )
        )

    async def async_added_to_hass(self) -> None:
        """Restore the switch state, falling back to migrated/default settings."""
        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        if previous is not None and previous.state in (STATE_ON, STATE_OFF):
            setattr(
                self._runtime.recording_preferences,
                self.entity_description.preference,
                previous.state == STATE_ON,
            )

    async def async_turn_on(self, **kwargs: object) -> None:
        """Enable this recording preference."""
        del kwargs
        setattr(
            self._runtime.recording_preferences,
            self.entity_description.preference,
            True,
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        """Disable this recording preference."""
        del kwargs
        setattr(
            self._runtime.recording_preferences,
            self.entity_description.preference,
            False,
        )
        self.async_write_ha_state()
