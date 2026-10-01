A reference implementation showing how a customer-facing application can use the Twilio stack — **TAC (Twilio Agent Connect)**, **ConversationRelay**, **Conversation Orchestrator**, **Conversation Memory**, **Conversation Intelligence**, and **Event Streams** — to run outbound voice + SMS conversations powered by an AI agent.

It sits between your system of record (EHR, OMS, CRM) or your business application and Twilio. Your systems decide *who* to reach, *why*, and under what rules — timezone, quiet hours, consent, retry budget, channel preference. This layer *enforces* those rules, runs the conversation across voice and SMS, and reports every outcome back so the record of truth stays in your systems.

A test harness exercises the flow for developers; a wallboard surfaces live state for operators.

Built in Python with FastAPI, with two Vite + React frontends. Monorepo managed by `uv`.

---

## Why you'd build this

Most businesses have systems of record that know *when* a customer needs to be contacted — the EHR knows tomorrow's appointments, the OMS knows which package is 20 minutes out, the growth database knows which users haven't opened the app in three weeks — but those systems weren't designed to run the actual conversation. 



A cron job that fires SMS from inside the CRM is enough until the first time it texts someone at 2 a.m., skips a time zone, double-dials on a retry, or has no record of whether the customer actually heard back.

Some use cases this blueprint is shaped around:

- Healthcare appointment confirmations and reminders
- Last-mile delivery communications
- Re-engaging quiet users (abandoned carts, lapsed subscriptions, dormant trials)
- Payment reminders and collections outreach
- Service outage or incident notifications with two-way acknowledgement


### A broker for conversations

If you've worked with a message queue, the shape will be familiar.

| Message queue | This blueprint |
|---|---|
| Producer publishes a message | Upstream app `POST /jobs` |
| Broker holds and routes work | Scheduler holds `Job`s, applies policy, picks the moment to fire |
| Delivery rules (retry, DLQ, ordering) | Quiet hours, consent, retries, channel fallback, dedupe, concurrency |
| Consumer processes the message | Agent-connect runs the LLM conversation over Twilio |
| Ack / nack back to producer | `upstream_callback_url` POSTs on each Job lifecycle event |
| Dead-letter queue | `JobRun.status = failed` with `terminal_reason`, surfaced in audit + wallboard |

The scheduler is in-process sqlite, for now.

---

## What's in the box

- **scheduler** — Accepts outreach requests from your upstream systems, enforces the rules each request carries (time window, consent, retry budget, channel fallback, dedupe, concurrency), dispatches to agent-connect when the moment is right, and POSTs outcomes back to the upstream.
- **agent-connect** — TAC-based service that connects your LLM to Twilio. Handles inbound Twilio webhooks and runs outbound voice (via ConversationRelay) and SMS conversations, with Conversation Memory wired in for identity resolution and persistent context.
- **event-ingestor** — Single consumer for Twilio Event Streams. Translates call status, message delivery, and Conversation Intelligence operator results into state transitions on the in-flight outreach, writes audit, and updates the wallboard.
- **test-harness** — React UI for submitting outreach requests and watching them flow end-to-end.
- **wallboard** — React UI for operators; live view of in-flight outreach and recent outcomes.
- **observability** — OpenTelemetry traces across every service and an append-only audit log for business events.


A **Job** is the unit of work your upstream system hands to the blueprint. It carries *who* to reach, *why*, and the rules under which the outreach is allowed to happen — timezone, quiet hours, consent state, retry budget, channel preference, callback URL. Each attempt the blueprint makes to fulfill a Job is a **JobRun**; a Job may produce several JobRuns as it retries or falls back across channels.



## System diagram

```
   ┌──────────────────────┐                      ┌──────────────────┐
   │ Upstream (CRM, etc.) │                      │   test-harness   │
   └──────────┬───────────┘                      └──────────┬───────┘
              │ POST /jobs                                  │ POST /jobs
              │        ┌────────────────────────────────────┘
              ▼        ▼
   ┌──────────────────┐    POST /outbound   ┌──────────────────┐
   │    scheduler     │ ──────────────────▶ │  agent-connect   │
   │                  │                     │      (TAC)       │
   └──────────▲───────┘                     └────────┬─────────┘
              │                                      │
              │ StatusCallback                       ▼
              │ (per call/msg)             ┌──────────────────┐
              └─────────────────────────── │      Twilio      │
                                           │  CR / Orch /     │
   ┌──────────────────┐                    │  Memory / Intel  │
   │  event-ingestor  │ ◀── Event Streams ─│                  │
   │     (sink)       │                    └────────┬─────────┘
   └─────────┬────────┘                             │
             │                                      │ inbound
             │ events                               ▼ webhooks
             │                             ┌──────────────────┐
             │                             │  agent-connect   │
             │                             └──────────────────┘
             ▼
   ┌─────────────────────────────────────────────────┐
   │                   wallboard                     │ 
   └─────────────────────────────────────────────────┘

```

## Services

### `apps/scheduler`


**Responsibilities**
- Accept `POST /jobs` from upstream apps and the test-harness.
- Run policy before firing: quiet hours in the recipient's timezone, do-not-contact suppression, dedupe on `(scenario, to)`, concurrency caps per campaign.
- Fire outbound by calling TAC's implementations in agent-connect.
- Advance `JobRun` state on per-call / per-message callbacks.
- Retry and channel fallback (voice no-answer → SMS).
- Report back to upstream via `upstream_callback_url` on each lifecycle transition.

**Folder layout**
```
apps/scheduler/src/scheduler/
├── main.py              # FastAPI app
├── http/                # /jobs, /jobs/{id}, /runs, /audit, /twilio/status
├── jobs/                # queue + JobRun lifecycle
├── policy/              # time-window, consent, dedupe, suppression
├── fallback/            # channel fallback rules
├── outbound/            # calls agent-connect; sets statusCallback URL
├── callbacks/           # Twilio StatusCallback handlers
└── infra/               # db, otel, config
```

### `apps/agent_connect`

Twilio's conversation middleware that connects your LLM to Twilio's channels.

**Responsibilities**
- Memory retrieval before each response — identity resolution + Recall against Conversation Memory.
- Orchestrator session management — Conversation + Communication state on the Twilio side.
- Tools (lookup account, schedule callback, transfer, etc.) called by the LLM mid-conversation.

### `apps/event_ingestor`

A sink for all account-level Twilio Event Streams and scheduler-emitted lifecycle events.

**Responsibilities**
- `POST /twilio/events` — webhook URL.
- Validate Twilio signature on every request using `RequestValidator`.
- Dedupe on event id via the `seen_events` sqlite table — Event Streams is at-least-once.

### `apps/test_harness`

Place single or batch test calls against the current agent, keep a history of past runs, and inspect what each conversation produced.

### `apps/wallboard`

Polls scheduler and event-ingestor every 2 seconds.

---

## Shared code (`shared/`)

A Python package `voice-blueprint-shared` that every backend app depends on as a `uv` workspace member.

```
shared/src/voice_blueprint_shared/
├── job.py       # Job + JobRun Pydantic models
├── audit.py     # audit.record(db, event) writer
└── otel.py      # initOtel(service_name) — one call per app
```

**Why shared, not duplicated:** three apps need the exact same `Job` shape, the same OTel init, and the same audit event schema. Duplication drifts.

**Why not a published package:** workspace symlink is enough; nothing is versioned or shipped independently.


### REST + HTTPS between services

No message bus. Every service exposes a plain JSON HTTP API. In dev, HTTP on localhost; in prod, HTTPS via whatever ingress the deploy target provides.

Trade-off accepted: higher latency and more coupling than a bus, but trivially understandable, debuggable, and testable. If an inter-service hop later needs a bus, event-ingestor is the natural first candidate.

---

## Twilio resources this blueprint uses

| Resource | Where it's provisioned | Where its ID is read |
|---|---|---|
| Memory Store | `scripts/provision.py` | `agent-connect` env, `scheduler` env |
| Orchestrator Configuration | `scripts/provision.py` | `agent-connect` env (passed in TwiML `conversationConfiguration`) |
| Intelligence Configuration | `scripts/provision.py` | Linked on the Orchestrator Config |
| Phone number | Manual (Twilio console) | `scheduler` env (default `from`); inbound webhooks on the number point at `agent-connect` |
| Event Streams sink | `scripts/provision.py` | Points at `event-ingestor` public URL |
| Per-call / per-message StatusCallback | Set at API call time by `scheduler` | Scheduler's own `/twilio/status` endpoint |

IDs are **env config**, not source — a fresh Twilio account produces a different set. `.env.example` enumerates them; `scripts/provision.py` creates the resources and writes IDs to `.env`.

---

## Running locally

### Prerequisites

- **Python 3.11+**
- **uv** — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Node 20+** (for the two Vite UIs)
- **honcho** — `uv tool install honcho`
- **ngrok** (or Twilio dev tunnel) — Twilio must reach your laptop for webhooks and ConversationRelay

### One-time setup

```bash
# Install Python deps for all workspace members
uv sync

# Install JS deps for the two UIs
npm --prefix apps/test_harness install
npm --prefix apps/wallboard install

# Provision Twilio resources + write IDs to .env
uv run python scripts/provision.py

# Start tunnels (two tunnels — one for agent-connect webhooks, one for event-ingestor)
ngrok start --all --config ngrok.yml
```

### Boot everything

```bash
honcho start
```

Ports:

| Service | URL |
|---|---|
| scheduler | http://localhost:3001 |
| agent-connect | http://localhost:3002 (+ wss for ConversationRelay) |
| event-ingestor | http://localhost:3003 |
| test-harness | http://localhost:5173 |
| wallboard | http://localhost:5174 |

### Try it

1. Open the test harness at http://localhost:5173
2. Upload `examples/sample_scenarios/jobs.sample.json`
3. Watch each job execute — transcript, memory, intelligence, status

---


---

## Observability

### Tracing

Every app calls `init_otel(service_name="scheduler")` (etc.) at startup. HTTP calls between services propagate `traceId` automatically, so a single trace spans:

```
POST /jobs (scheduler)
 └─ policy check
     └─ POST /outbound (agent-connect)
         └─ Twilio Calls.create
         └─ ConversationRelay WS session
             └─ LLM request
```

Point `OTEL_EXPORTER_OTLP_ENDPOINT` at any OTel backend.

### Auditing

Every meaningful business event appends to `audit.db`:

```python
audit.record(
    actor="scheduler",
    action="job.suppressed",
    subject=job.id,
    data={"reason": "quiet_hours", "local_time": "22:45"},
)
```

Wallboard reads from `GET /scheduler/audit?since=...&kind=...`.

### Metrics

OTel metrics (counters, histograms) emitted by scheduler and event-ingestor. Wallboard polls `GET /scheduler/stats` for the live summary; metrics also go to the OTel backend for alerting.

---

## Compliance posture

The blueprint demonstrates — but does not fully implement — these guardrails:

- **TCPA quiet hours** — policy check in scheduler (`constraints.allowed_hours_local`)
- **Consent** — `consent` field on Job; scheduler refuses to fire marketing SMS without it
- **Do-not-contact** — suppression list check (sqlite table, swappable for prod source)
- **PCI** — ConversationRelay is explicitly used in modes compatible with PCI patterns; no payment capture in the sample scenarios
- **HIPAA** — not configured in this blueprint; see Twilio HIPAA skill for enablement

For production use, each item needs real backing data and policy sign-off from the customer's compliance team.

---
