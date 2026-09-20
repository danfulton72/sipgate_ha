"""Constants for the sipgate.io integration."""

from typing import Final

DOMAIN: Final = "sipgate_ha"
NAME: Final = "sipgate.io"

API_BASE_URL: Final = "https://api.sipgate.com/v2"

CONF_TOKEN_ID: Final = "token_id"
CONF_PUBLIC_URL: Final = "public_url"
CONF_CONTACTS: Final = "contacts"
CONF_INCLUDE_OUTGOING: Final = "include_outgoing"
CONF_SIGNIFICANT_DIGITS: Final = "significant_digits"

DEFAULT_INCLUDE_OUTGOING: Final = False
DEFAULT_SIGNIFICANT_DIGITS: Final = 9

EVENT_CALL_STARTED: Final = "sipgate_call_started"
EVENT_CALL_ANSWERED: Final = "sipgate_call_answered"
EVENT_CALL_ENDED: Final = "sipgate_call_ended"

SERVICE_HANG_UP: Final = "hang_up"
ATTR_CALL_ID: Final = "call_id"
