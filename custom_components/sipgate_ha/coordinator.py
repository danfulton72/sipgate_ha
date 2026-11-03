"""Data coordinator for sipgate call history."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .account_type import SipgateAccountType
from .api import (
    SipgateApiError,
    SipgateAuthenticationError,
    SipgateAuthorizationError,
    SipgateClient,
    SipgateConnectionError,
    event_sort_key,
)
from .const import DEFAULT_HISTORY_LIMIT, NAME

_LOGGER = logging.getLogger(__name__)


class SipgateHistoryCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Poll a small, bounded window of recent call history."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SipgateClient,
        refresh_minutes: int,
        account_type: SipgateAccountType,
    ) -> None:
        """Initialize the coordinator."""
        update_interval = (
            timedelta(minutes=refresh_minutes) if refresh_minutes > 0 else None
        )
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{NAME} call history",
            update_interval=update_interval,
        )
        self.client = client
        self.account_type = account_type
        self.data = []

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Fetch recent calls from classic history or sipgate Neo channel events."""
        try:
            if await self.account_type.async_is_neo():
                return await self._async_fetch_channel_events()
            return await self.client.async_get_call_history(DEFAULT_HISTORY_LIMIT)
        except SipgateAuthorizationError as err:
            raise UpdateFailed(
                "The sipgate token is not allowed to read call history. Classic "
                "accounts need history:read; on sipgate Neo the token's user must "
                "also be a member of each channel"
            ) from err
        except SipgateAuthenticationError as err:
            raise UpdateFailed("sipgate rejected the configured credentials") from err
        except SipgateConnectionError as err:
            raise UpdateFailed("Could not connect to sipgate") from err
        except SipgateApiError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_fetch_channel_events(self) -> list[dict[str, Any]]:
        """Merge the newest events across the configured or discovered channels."""
        channel_ids = await self.account_type.async_channel_ids()
        if not channel_ids:
            raise UpdateFailed(
                "No sipgate Neo channels found. Set channel IDs in the "
                "sipgate.io integration options"
            )

        events: list[dict[str, Any]] = []
        for channel_id in channel_ids:
            events.extend(
                await self.client.async_get_channel_events(
                    channel_id, DEFAULT_HISTORY_LIMIT
                )
            )
        events.sort(key=event_sort_key, reverse=True)
        return events[:DEFAULT_HISTORY_LIMIT]
