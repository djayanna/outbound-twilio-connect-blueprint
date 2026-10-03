# Overview

A reference implementation of a conversation broker in front of Twilio. Your systems of record (EHR, OMS, CRM, growth DB) decide *who* to reach, *why*, and *under what rules*; this blueprint enforces those rules, runs the conversation across voice and SMS using **TAC**, **ConversationRelay**, **Conversation Orchestrator**, **Conversation Memory**, **Conversation Intelligence**, and **Event Streams**, and reports every outcome back so the record of truth stays upstream.

## Services

```
     POST /jobs
upstream ───────▶ scheduler ───────▶ agent-connect ───▶ Twilio
     ◀────────                       (TAC + LLM)        │
upstream_callback_url                       ▲           │
                                            │           ▼
                       event-ingestor ◀─────┴── Event Streams
```

| Service | Port | Role |
|---|---|---|
| **scheduler** | 3001 | Owns Jobs, JobRuns, SQLite audit + queue, every business policy. The firing loop lives here. |
| **agent-connect** | 3002 | TAC application. Inbound TwiML/WebSocket/SMS webhook; outbound initiation. Scenario-aware system prompt + OpenAI + Twilio Memory + function tools. |
| **event-ingestor** | 3003 | Single sink for Twilio Event Streams + scheduler lifecycle events. Validates, dedupes, forwards state-changing events to the scheduler. |
| **test-harness** | 5173 | Developer UI — single/batch/bulk job submission, live call history, run + audit inspector. |
| **wallboard** | 5174 | Operator UI — live metrics, queue depth, line capacity, audit tail. |

Shared `voice_blueprint_shared` package provides `Job`/`JobRun`/`Consent`/`Constraints` models, an append-only audit writer, and OpenTelemetry init.

## Request lifecycle (voice happy path)

1. Upstream POSTs a `Job` to `scheduler /jobs` with a signed API key.
2. Scheduler runs the policy chain: DNC → consent → quiet hours (timezone-derived from the E.164 number) → dedupe. If accepted it writes the Job to SQLite with status `firing`.
3. The in-process worker tick picks it up, creates a `JobRun(attempt=1, status=queued)`, and POSTs the Job to `agent-connect /outbound`.
4. agent-connect calls `twilio.calls.create(...)` with `url=/twiml` and `status_callback=/twilio/status` pointing back at the scheduler.
5. Twilio dials. On answer it fetches TwiML from TAC's `/twiml`; TAC emits `<Connect><ConversationRelay>` and opens the WebSocket.
6. For each turn: caller speaks → STT → `on_message_ready` runs the scenario-aware prompt + Memory-wrapped OpenAI call + optional tools → TTS → audio streamed back.
7. Twilio POSTs each state change (initiated/ringing/answered/completed) to the scheduler's `/twilio/status`. The handler translates to our `RunStatus` and audits.
8. On terminal failure (`no-answer`, `busy`, `failed`), scheduler consults the retry policy + channel-fallback rules. Voice no-answer → the next attempt dispatches as SMS.
9. Every lifecycle event is POSTed to the Job's `upstream_callback_url` with an `X-Blueprint-Signature` HMAC header. Scheduler audits locally; event-ingestor audits Twilio-originated events — the two logs are intentionally distinct.

## Where things live

- **Policy chain**: `apps/scheduler/src/scheduler/policy/__init__.py` composes DNC → consent → quiet-hours → dedupe.
- **Firing loop**: `apps/scheduler/src/scheduler/worker/loop.py` runs on a 1-second tick in-process.
- **Status round-trip**: `apps/scheduler/src/scheduler/http/callbacks.py` handles `/twilio/status` and `/internal/events`.
- **Scenario registry**: `apps/agent_connect/src/agent_connect/prompts/__init__.py` + `tools/__init__.py`.
- **Message handler**: `apps/agent_connect/src/agent_connect/main.py:_handle_message_ready`.

See [01-local-setup.md](./01-local-setup.md) to run it.
