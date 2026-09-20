"""Data coordinator for sipgate call history."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    SipgateApiError,
    SipgateAuthenticationError,
    SipgateAuthorizationError,
    SipgateClient,
    SipgateConnectionError,
)
from .const import DEFAULT_HISTORY_LIMIT, NAME

_LOGGER = logging.getLogger(__name__)


class SipgateHistoryCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Poll a small, bounded window of recent call history."""

    def __init__(self, hass: HomeAssistant, client: SipgateClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{NAME} call history",
            update_interval=timedelta(minutes=5),
        )
        self.client = client
        self.data = []

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Fetch recent CALL history entries."""
        try:
            return await self.client.async_get_call_history(DEFAULT_HISTORY_LIMIT)
        except SipgateAuthorizationError as err:
            raise UpdateFailed(
                "The sipgate token requires history:read for call history"
            ) from err
        except SipgateAuthenticationError as err:
            raise UpdateFailed("sipgate rejected the configured credentials") from err
        except SipgateConnectionError as err:
            raise UpdateFailed("Could not connect to sipgate") from err
        except SipgateApiError as err:
            raise UpdateFailed(str(err)) from err
