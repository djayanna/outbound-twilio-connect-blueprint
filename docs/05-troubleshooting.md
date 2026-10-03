# Troubleshooting

## Services

### scheduler says "run.unmatched" for every status callback

The scheduler couldn't find a JobRun with a matching `CallSid` / `MessageSid`. Possibilities:

- The outbound call happened before T1.5 landed and didn't record the SID. Submit a fresh Job.
- You're pointing Twilio's status callback at a different scheduler instance than the one that initiated the call. Verify `SCHEDULER_PUBLIC_URL` matches the ingress your Twilio Call was created with.
- You're sending Event Streams events to `/internal/events` from event-ingestor but the Job was created on a scheduler instance running against a different SQLite file. Check `JOBS_DB_PATH`.

### `scripts/provision.py` → 404 `20404` on `POST /v1/Services`

Full error:

```
Twilio API error: 404 {"code":20404,"message":"The requested resource /v1/Services was not found", …}
```

Conversation Memory is a Twilio product that must be **enabled on your account** before `memory.twilio.com/v1/Services` becomes reachable. Twilio returns 20404 on accounts that don't have it.

Fix:
1. Go to the Twilio Console → **Products** → look for "Conversation Memory" (or "Memora" on older consoles) and request access / enable.
2. If it's not listed at all, contact your Twilio account team or support — Memory is still gated by region/tier on some accounts.
3. Re-run `scripts/provision.py`.

Workaround while you wait: provision.py now skips Memory on 20404 and continues with the rest of the stack. The Orchestrator Configuration is created without `memoryStoreId`; agent-connect runs with Memory recall disabled but everything else (voice, SMS, retry/fallback, AMD, Intelligence Summary + Sentiment) works. Fill in `TWILIO_MEMORY_STORE_ID` and re-run provision once the product is enabled.

### agent-connect boots but TAC routes don't exist

The warning line in logs will say:

```
TAC not initialized (likely missing/invalid Twilio creds): …
```

TAC calls Twilio's Conversation Orchestrator REST API on `__init__` to fetch the Configuration. Run `uv run python scripts/provision.py` to create it and populate `TWILIO_CONVERSATION_CONFIGURATION_ID` in `.env`, then restart agent-connect.

### event-ingestor returns 401 on every event

Twilio Event Streams signs the request HMAC-SHA1 over **just the URL** (JSON sinks don't include the body). Make sure:

- `TWILIO_AUTH_TOKEN` matches the account the sink was created on.
- The public URL Twilio delivers to (as written in the sink config) matches exactly what reaches your service (schemes, trailing slashes, port forwarding).

Set `DEV_MODE=1` and clear `TWILIO_AUTH_TOKEN` to confirm the plumbing works without signatures. **Never** run prod this way.

## ngrok

### Twilio can't reach my service even though curl works

- ngrok free tier rotates the public hostname on every restart. If you restart tunnels, update `.env` and restart affected services.
- WebSocket (ConversationRelay) requires `wss://` — ngrok supports it on `https://` tunnels only; `http://` tunnels will fail.

### "signature invalid" after moving laptops / networks

If your tunnel URL has changed, the signature Twilio computes is over the URL it was configured with on the sink. Update the sink via `scripts/provision.py` (recreate it with the new URL).

## Policy

### My job is suppressed with reason `outside_allowed_hours:… @ America/New_York` but my test number is in LA

Timezone is resolved from the country code of the phone number. US → `America/New_York` by default (conservative latest-sunset). Set `job.constraints.timezone = "America/Los_Angeles"` explicitly on every outreach where you know the local zone.

### Dedupe is firing on jobs I expect to go through

`DEDUPE_WINDOW_SECONDS` defaults to 3600. Submit with a different `scenario`, use a different `job.id` while targeting the same number (idempotency on `id` takes precedence over dedupe), or lower the window.

## OpenAI

### on_message_ready returns stub replies

`OPENAI_API_KEY` isn't set. The agent-connect module logs the warning and returns `[scenario] (stub) You said: <input>` so you can smoke-test TAC without burning credit.

### Models return odd output format

`OPENAI_MODEL` defaults to `gpt-4o-mini`. Override via env. Scenarios instruct the model to avoid markdown — if it ignores, your deployed `OPENAI_MODEL` may not follow instructions well; try a stronger model.
