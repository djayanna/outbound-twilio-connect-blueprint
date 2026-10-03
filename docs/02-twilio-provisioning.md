# Twilio provisioning

`scripts/provision.py` creates every Twilio resource the blueprint needs and writes the resulting SIDs to your `.env`. Running it is idempotent only in the sense that each call creates fresh resources — rerun if you need to start over.

## What gets created

| Resource | Twilio product | Env var it populates |
|---|---|---|
| Memory Store | Conversation Memory | `TWILIO_MEMORY_STORE_ID` |
| Orchestrator Configuration | Conversation Orchestrator | `TWILIO_CONVERSATION_CONFIGURATION_ID` |
| Intelligence Configuration | Conversation Intelligence | `TWILIO_INTELLIGENCE_CONFIGURATION_ID` |
| Event Streams webhook sink | Event Streams | `TWILIO_EVENT_STREAMS_SINK_SID` |

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

One rule, with the Twilio-authored `Summary` operator wired to fire at `CONVERSATION_END`. Add your own operators (sentiment, consent-capture, intent, etc.) by appending to the `operators` array.

## Event Streams sink

JSON webhook sink pointing at `${EVENT_INGESTOR_PUBLIC_URL}/twilio/events` with `batch_events: true`. The signature over the body is HMAC-SHA1 over just the URL — see [`event_ingestor/validation.py`](../apps/event_ingestor/src/event_ingestor/validation.py) for how we verify.
