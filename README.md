# sipgate.io → Home Assistant call notifier

Actionable "incoming call" notifications in Home Assistant, with caller-name
resolution and a Hang up button. No SIP registration, no softphone container.

```
  sipgate.io  ──POST newCall──▶  bridge  ──event──▶  Home Assistant
       ▲                            │                      │
       │◀──── XML (onAnswer/onHangup)                       │ notification
       │                                                    ▼
       └──────── DELETE /v2/calls/{callId} ◀──── rest_command ◀── "Hang up" tapped
```

## Before you build anything: the five-minute test

Everything here hinges on one undocumented question — **can you hang up a call
that is still ringing?** RTCM is described as modifying *running* calls, and it
is not stated whether an unanswered inbound call qualifies.

Create a Personal Access Token in the sipgate web console, then ring your own
sipgate number and, while it is still ringing, run:

```bash
curl -s -u "token-XXXX-0:your-token" https://api.sipgate.com/v2/calls | jq
```

- **Call is listed** → everything below works as written. Note the `callId` and
  try `curl -X DELETE -u ... https://api.sipgate.com/v2/calls/<callId>` to
  confirm.
- **Empty array** → the notification and caller ID still work perfectly; the
  Hang up button won't. See *Fallbacks* at the bottom.

## Setup

### 1. Book sipgate.io

The push API needs a package on your account. The most basic one is the free
sipgate.io **S** package. On sipgate basic or simquadrat you book it in the
product's feature store; as a sipgate team admin it's under *Account
Administration → Plans & Packages*.

### 2. Create credentials

- **Home Assistant long-lived access token** — your HA profile page, bottom.
- **sipgate Personal Access Token** — sipgate web console. Give it the
  call-manipulation scopes (you'll see them listed when creating it). Note both
  the token **ID** and the token itself; they're used as HTTP Basic
  username/password.

Build the header value for `secrets.yaml`:

```bash
echo "Basic $(printf 'token-XXXX-0:your-personal-access-token' | base64 -w0)"
```

### 3. Deploy the bridge

```bash
cp .env.example .env
openssl rand -hex 32          # put this in both WEBHOOK_TOKEN and PUBLIC_BASE
cp data/contacts.example.json data/contacts.json
$EDITOR .env data/contacts.json
docker compose up -d --build
```

`PUBLIC_BASE` must be the full external HTTPS prefix **including** the token,
e.g. `https://calls.example.com/8f3a1c...`. It's baked into the
`onAnswer`/`onHangup` attributes sipgate calls back on, so it has to be
absolute and resolvable from sipgate's network.

Put it behind whatever reverse proxy you already run. sipgate's own docs
strongly discourage plain HTTP here, since the payloads carry call metadata.

### 4. Point sipgate at it

1. Go to `console.sipgate.com` and log in.
2. *Webhooks → URLs* in the left menu.
3. Gear icon on the **Incoming** entry.
4. Set `https://calls.example.com/<token>/newcall` and save.
5. In the sources section, pick which phonelines and groups should fire it.

### 5. Home Assistant

Copy the blocks from `homeassistant.yaml` into your config, replacing
`notify.mobile_app_YOUR_PHONE` with your device. Restart, then simulate a call
without bothering anyone:

```bash
curl -X POST \
  --data "event=newCall&from=442071234567&to=4915791234567&direction=in&callId=test123&user[]=Alice&userId[]=w0" \
  https://calls.example.com/<token>/newcall
```

You should get XML back and a notification on your phone. Clear it with:

```bash
curl -X POST --data "event=hangup&cause=cancel&callId=test123&direction=in" \
  https://calls.example.com/<token>/hangup
```

## Notes on the design

**Why a bridge at all.** HA's webhook trigger always answers 200 with an empty
body. sipgate wants XML, and the `onAnswer`/`onHangup` subscription only exists
inside that XML. Hence ~200 lines of shim.

**Latency matters.** The `newCall` handler sits in the call-setup path — the
phone doesn't ring until you answer. The handler builds a string and returns;
the HA call is dispatched as a background task.

**Number formats.** sipgate sends `from` without a leading `+`
(`492111234567`), or the literal `anonymous` for withheld. Contact matching
uses the last 9 digits so `+442071234567`, `02071234567` and `00442071234567`
all resolve to the same person.

**`user[]` is always an array**, even for one user, because group calls ring
several people at once.

**No webhook signatures.** sipgate doesn't sign its pushes. The unguessable
path segment is the whole of your authentication — keep it long and rotate it
if it leaks. An IP allowlist on your proxy is a reasonable second layer.

**Push latency.** FCM/APNS delivery is usually 1–3s but isn't guaranteed. On a
call that rings for 20 seconds that's tight. The Android companion app's local
push (via the HA websocket, when on your own network) is noticeably faster if
you have it available.

## Fallbacks if you can't hang up a ringing call

In rough order of how much I'd recommend them:

**1. Persistent blocklist (best).** Change the Hang up button to "Block this
number". It writes to a JSON file the bridge reads, and future calls from that
number get an immediate `<Reject reason="busy"/>` in the `newCall` response.
This is what the push API is genuinely designed for, it works with total
reliability, and after a couple of weeks of tapping it you'll rarely be
bothered again. The current call still rings out, which is the trade.

**2. Voicemail diversion on a known-bad list.** Same mechanism, but respond
with `<Dial><Voicemail /></Dial>` instead — the caller can leave a message.
Requires the voicemail feature booked.

**3. Hold the webhook open.** Delay the XML response for 3–5 seconds while
polling a decision flag that the notification action sets. sipgate's docs note
this effect explicitly for `Gather`: call establishment is delayed until the
timeout elapses. It technically gives you a real "reject this one" button, but
it adds several seconds of silence to *every* call before your phone rings, and
you're gambling on sipgate's undocumented response timeout. I wouldn't ship it.

**4. Reverse the default.** Respond to every unknown number with a `<Gather>`
that plays a short "press 1 to be connected" prompt. Kills automated dialers
outright, at the cost of mildly annoying every human who isn't in your
contacts.

## A word on sipgate neo

If your account predates September 2025 you're on sipgate classic, which is
what this targets. Accounts are being migrated to neo gradually, and on neo
**channels replace groups and phonelines** — which is exactly the concept the
webhook source selection in step 4 uses. Check `featureScope` in your JWT
(`CLASSIC_PBX` vs `NEO_PBX`) before debugging anything that used to work.
