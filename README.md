# sipgate.io for Home Assistant

A native Home Assistant custom integration for **sipgate.io call webhooks**.
It receives `newCall`, `answer`, and `hangup` events directly inside Home
Assistant, fires Home Assistant events for automations, resolves optional local
caller-name mappings, and provides a `sipgate_ha.hang_up` action for real-time
call control.

There is no sidecar container, no long-lived Home Assistant access token, and
no YAML required to configure the integration itself.

## Requirements

- Home Assistant **2026.9.0 or newer**.
- A sipgate account with sipgate.io push webhooks enabled.
- A sipgate Personal Access Token (PAT) with `account:read`. Add `rtcm:write` only if you want to use the `sipgate_ha.hang_up` action.
- A Home Assistant URL that sipgate can reach from the internet. HTTPS is
  strongly recommended by sipgate.

## Installation

### HACS custom repository

1. In HACS, open **Integrations** and add this repository as a custom repository
   of type **Integration**.
2. Install **sipgate.io**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → sipgate.io**.

You can also install manually by copying `custom_components/sipgate_ha` into
Home Assistant's `custom_components` directory and restarting Home Assistant.

## Setup

During the UI setup flow enter:

- the sipgate PAT ID;
- the PAT secret;
- your externally reachable Home Assistant base URL, for example
  `https://ha.example.com` or your Home Assistant Cloud remote URL.

The integration validates the PAT against sipgate's documented `/v2/account` endpoint and
then generates a cryptographically random Home Assistant webhook ID. The final
setup step displays the complete webhook URL.

In the sipgate web console, set **Incoming calls** to that URL. The integration
returns the XML that subscribes the same URL to sipgate's `onAnswer` and
`onHangup` callbacks, so only one URL is required.

> Treat the webhook URL as a secret. Home Assistant webhook endpoints are
> intentionally unauthenticated; the random webhook ID is the bearer secret.

## Home Assistant events

The integration fires these events:

- `sipgate_call_started`
- `sipgate_call_answered`
- `sipgate_call_ended`

A `sipgate_call_started` event contains fields such as:

```yaml
call_id: ABC123
from: "+442071234567"
to: "+441234567890"
name: Mum
display: "Mum (+442071234567)"
known: true
anonymous: false
users:
  - Alice
user_ids:
  - w0
```

The event names intentionally match the original container bridge so existing
automations need minimal changes.

## Hang up action

Use the native action instead of a `rest_command`:

```yaml
action: sipgate_ha.hang_up
data:
  call_id: "{{ trigger.event.data.call_id }}"
```

sipgate documents `DELETE /v2/calls/{callId}` for terminating a running call.
The `sipgate_ha.hang_up` action has been verified against a live incoming
sipgate call, including while the call is ringing.

## Actionable mobile notification package

A complete package is included at
[`examples/sipgate_package.yaml`](examples/sipgate_package.yaml). It:

- shows an incoming-call notification using the resolved caller name/number;
- provides **OK** and **Hang up** buttons;
- calls `sipgate_ha.hang_up` for the Hang up action;
- clears the notification when the user presses OK, the call is answered, or
  the call ends.

Replace `notify.mobile_app_your_phone` with your Companion App notify action.

If you use Home Assistant packages, enable them once in `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Then copy the example to `/config/packages/sipgate.yaml`, update the notify
action, and restart Home Assistant.

## Caller names

Open the integration's **Configure** dialog to add optional contact mappings.
Use one mapping per line:

```text
+442071234567=Mum
02089998888=Dentist
+447700900123=Sam
```

By default, matching uses the final 9 digits, allowing national and
international representations of the same number to match. The number of
significant digits is configurable from 7 to 15.

Outgoing `newCall` events are ignored by default and can also be enabled from
integration options.

## Architecture

```text
sipgate.io
    │  POST application/x-www-form-urlencoded
    ▼
Home Assistant /api/webhook/<random-id>
    │
    ├─ newCall ──► fire sipgate_call_started + return callback XML
    ├─ answer  ──► fire sipgate_call_answered
    └─ hangup  ──► fire sipgate_call_ended

Home Assistant automation
    │
    └─ sipgate_ha.hang_up ──► DELETE api.sipgate.com/v2/calls/<callId>
```

The `newCall` path intentionally performs no outbound API request before
returning the XML response. This keeps Home Assistant's part of sipgate's call
setup path as short as practical.

## Development

The repository includes Home Assistant-style pytest tests, Ruff, hassfest and
HACS validation.

```bash
python -m pip install -r requirements-test.txt
ruff check .
ruff format --check .
pytest --cov=custom_components/sipgate_ha --cov-report=term-missing
```

CI runs the same checks on every pull request and push to `main`.

## Troubleshooting

If setup fails before sipgate is contacted, make sure **Personal Access Token
ID** contains only the token ID, such as `token-ABC123-0`. Do not paste a
combined `ID:secret` value or a complete `Basic ...` authorization header.

The integration reports invalid PAT format, rejected credentials,
missing `account:read`, connection failures, and unexpected sipgate HTTP
responses separately.

## Security and privacy

- The sipgate PAT is stored in the Home Assistant config entry and is redacted
  from diagnostics.
- The webhook ID is generated with Home Assistant's cryptographically secure
  webhook helper and is also redacted from diagnostics.
- Caller mappings are local Home Assistant options and are redacted from
  diagnostics.
- sipgate recommends HTTPS for push webhooks because call metadata is sensitive.

## License

MIT
