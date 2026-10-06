# Twilio provisioning

`scripts/provision.py` creates every Twilio resource the blueprint needs and writes the resulting SIDs to your `.env`. The script is **idempotent**: if an SID is already in `.env` and the resource still exists on Twilio (the script `GET`s each one to confirm), the SID is reused and nothing new is created. Rerun it any time — adding env vars, moving a tunnel URL, or picking up a new type in the subscription list — without producing duplicate resources on your account.

Pass `--force` to recreate everything from scratch (useful after changing resource names or the Configuration shape):

```bash
uv run python scripts/provision.py          # idempotent (default)
uv run python scripts/provision.py --force  # recreate all
```

Stale SIDs (ones that point at resources since deleted) are detected via the GET probe and recreated automatically — no need for `--force` in that case.

## What gets created

| Resource | Twilio product | Env var it populates |
|---|---|---|
| Memory Store | Conversation Memory | `TWILIO_MEMORY_STORE_ID` |
| Orchestrator Configuration | Conversation Orchestrator | `TWILIO_CONVERSATION_CONFIGURATION_ID` |
| Intelligence Configuration | Conversation Intelligence | `TWILIO_INTELLIGENCE_CONFIGURATION_ID` |
| Event Streams webhook sink | Event Streams | `TWILIO_EVENT_STREAMS_SINK_SID` |
| Event Streams subscription | Event Streams | `TWILIO_EVENT_STREAMS_SUBSCRIPTION_SID` |

Phone number is **not** created — buy one in the Twilio console and set `TWILIO_PHONE_NUMBER` yourself. Inbound SMS/voice webhooks on that number should point at agent-connect (`https://${TWILIO_VOICE_PUBLIC_DOMAIN}/twiml` for voice, `/sms` for SMS — both mounted by TAC).

## Prerequisites in `.env` before running

```
TWILIO_ACCOUNT_SID=ACxxxx…
TWILIO_AUTH_TOKEN=…
TWILIO_PHONE_NUMBER=+15550000000
EVENT_INGESTOR_PUBLIC_URL=https://xxxx.ngrok.app
```

## Run

```bash
uv sync --group provision
uv run python scripts/provision.py
```

The script writes updated keys back into `.env`. If a line is already there, it's overwritten.

## Orchestrator Configuration details

- `conversationGroupingType: GROUP_BY_PROFILE` — one Memory profile per caller phone number.
- `memoryExtractionEnabled: true` — observations get written back on hangup.
- SMS capture rules whitelist your `TWILIO_PHONE_NUMBER` in both directions.
- VOICE channel has **no capture rules** — ConversationRelay is already active TwiML, and double-STT costs more than it's worth.

## Intelligence Configuration details

One rule, firing at `CONVERSATION_END` (post-call), with two Twilio-authored operators:

| Operator | SID | What you get |
|---|---|---|
| **Summary** | `intelligence_operator_01kcv35pnkeysaf6z6cqtbpegn` | 3–5 sentence human-readable summary. Populates the Inspector panel in the test-harness. |
| **Sentiment** | `intelligence_operator_01kcrvw16kfa88qvgrfmr7y151` | `positive` / `negative` / `neutral` / `mixed` on the full conversation. |

Edit `INTELLIGENCE_OPERATORS` at the top of `scripts/provision.py` to add more. Twilio also publishes:

- Script Adherence (`intelligence_operator_01kf34tcyefpyb1t4m0nbd8rxg`) — real-time, pair with `TRANSCRIPT_SEGMENT`.
- Next Best Response (`intelligence_operator_01kea27sy7ffsafmtsfp17nzx4`) — agent-assist.

For **consent capture, intent extraction, or payment-commitment detection**, create a **custom operator** in the Twilio console → Conversation Intelligence → Operators, copy its SID (format `intelligence_operator_*` or classic `LY*`), and paste it into `INTELLIGENCE_OPERATORS`. The shape is identical to prebuilt operators.

Operator results arrive at event-ingestor as `com.twilio.intelligence.operator-result.created` events (already in `SUBSCRIPTION_TYPES`) and are forwarded to the scheduler's `/internal/events`, which audits them. The test-harness Inspector surfaces any audit entry whose `action` contains `operator-result` under its "intelligence" block.

## Event Streams sink + subscription

Twilio Event Streams is a two-step model:

1. **Sink** — where events go. We create a JSON webhook sink pointing at `${EVENT_INGESTOR_PUBLIC_URL}/twilio/events` with `batch_events: true`. The signature over the body is HMAC-SHA1 over just the URL — see [`event_ingestor/validation.py`](../apps/event_ingestor/src/event_ingestor/validation.py) for how we verify.
2. **Subscription** — *which event types* flow into the sink. A sink with no subscription receives nothing.

The subscribed types match what [`event_ingestor/routing.py`](../apps/event_ingestor/src/event_ingestor/routing.py) filters on:

| Family | Why we subscribe |
|---|---|
| `com.twilio.voice.status-callback.call.*` (initiated / ringing / answered / completed) | Backchannel for the voice lifecycle. The scheduler also receives these via the per-call `statusCallback`; Event Streams covers inbound and ad-hoc calls that bypass our outbound path. |
| `com.twilio.messaging.message.*` (sent / delivered / undelivered / failed) | Same story for SMS. |
| `com.twilio.intelligence.operator-result.created` | **Only arrives via Event Streams** — this is why the subscription is mandatory. Scheduler attaches the result to the matching JobRun. |

The exact list lives in `scripts/provision.py:SUBSCRIPTION_TYPES`. If the Create call fails with "unknown type" or "schema mismatch", browse `https://events.twilio.com/v1/Types` or the Twilio console → Events → Types, update the list, re-run.
