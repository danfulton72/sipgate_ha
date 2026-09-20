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
CONF_HISTORY_REFRESH_MINUTES: Final = "history_refresh_minutes"

DEFAULT_INCLUDE_OUTGOING: Final = False
DEFAULT_SIGNIFICANT_DIGITS: Final = 9
DEFAULT_HISTORY_LIMIT: Final = 10
DEFAULT_HISTORY_REFRESH_MINUTES: Final = 0

EVENT_CALL_STARTED: Final = "sipgate_call_started"
EVENT_CALL_ANSWERED: Final = "sipgate_call_answered"
EVENT_CALL_ENDED: Final = "sipgate_call_ended"

SERVICE_HANG_UP: Final = "hang_up"
SERVICE_START_RECORDING: Final = "start_recording"
SERVICE_STOP_RECORDING: Final = "stop_recording"
SERVICE_CLICK_TO_CALL: Final = "click_to_call"
SERVICE_SEND_SMS: Final = "send_sms"

ATTR_CALL_ID: Final = "call_id"
ATTR_ANNOUNCEMENT: Final = "announcement"
ATTR_FROM: Final = "from"
ATTR_TO: Final = "to"
ATTR_DEVICE_ID: Final = "device_id"
ATTR_CALLER_ID: Final = "caller_id"
ATTR_SMS_ID: Final = "sms_id"
ATTR_RECIPIENT: Final = "recipient"
ATTR_MESSAGE: Final = "message"
