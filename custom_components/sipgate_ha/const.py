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
CONF_ACCOUNT_TYPE: Final = "account_type"
CONF_CHANNEL_IDS: Final = "channel_ids"
LEGACY_CONF_AUTO_RECORD_CALLS: Final = "auto_record_calls"
LEGACY_CONF_AUTO_RECORD_ANNOUNCEMENT: Final = "auto_record_announcement"

DEFAULT_INCLUDE_OUTGOING: Final = False
DEFAULT_SIGNIFICANT_DIGITS: Final = 9
DEFAULT_HISTORY_LIMIT: Final = 10
DEFAULT_HISTORY_REFRESH_MINUTES: Final = 0
DEFAULT_AUTO_RECORD_CALLS: Final = False
DEFAULT_AUTO_RECORD_ANNOUNCEMENT: Final = False

ACCOUNT_TYPE_AUTO: Final = "auto"
ACCOUNT_TYPE_CLASSIC: Final = "classic"
ACCOUNT_TYPE_NEO: Final = "neo"
ACCOUNT_TYPES: Final = (ACCOUNT_TYPE_AUTO, ACCOUNT_TYPE_CLASSIC, ACCOUNT_TYPE_NEO)
DEFAULT_ACCOUNT_TYPE: Final = ACCOUNT_TYPE_AUTO
DEFAULT_CHANNEL_IDS: Final = ""
# How long an automatic "classic" detection is trusted before probing again, so a
# running Home Assistant notices the sipgate Neo upgrade without a restart.
CLASSIC_RECHECK_SECONDS: Final = 6 * 60 * 60
# Upper bound on channels queried when no channel IDs are configured.
MAX_AUTO_CHANNELS: Final = 5

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
ATTR_CHANNEL_ID: Final = "channel_id"
