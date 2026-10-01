# voice-blueprint

A reference implementation showing how a customer-facing application can use the Twilio stack — **TAC (Twilio Agent Connect)**, **ConversationRelay**, **Conversation Orchestrator**, **Conversation Memory**, **Conversation Intelligence**, and **Event Streams** — to run inbound and outbound voice + SMS conversations driven by an LLM agent, with a scheduler that owns the business logic for when and how to reach out, a test harness for developers, and a wallboard for operators.

Built in Python with FastAPI, with two Vite + React frontends. Monorepo managed by `uv`.

---

## What this blueprint shows

1. **How to post work to a scheduler** rather than making Twilio calls directly from your app. Any upstream system (CRM, billing, portal) creates a `Job`; the scheduler decides when, how, and whether to execute it.
2. **How the scheduler enforces business policy** — time windows, consent, do-not-contact, retries, channel fallback, dedupe, concurrency.
3. **How TAC bridges your LLM agent to Twilio channels** — one application handles inbound webhooks and outbound conversations across voice (ConversationRelay) and SMS, with Conversation Memory wired in for identity resolution and persistent context.
4. **How Twilio Event Streams feeds state back** — call status, message delivery, Conversation Intelligence operator results — through a single ingestor that advances `JobRun` state, writes audit, and updates the wallboard.
5. **How to observe the system end-to-end** — OpenTelemetry traces across every service, an append-only audit log for business events, and a live wallboard for operators.

---

## System diagram

```
                        ┌──────────────────────────────┐
                        │  Upstream apps (CRM, portal) │
                        └──────────────┬───────────────┘
                                       │ POST /jobs
                                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              scheduler                                  │
│  • Validates Job (Pydantic)                                             │
│  • Runs policy: quiet hours, consent, DNC, dedupe, concurrency          │
│  • Owns the queue + JobRun lifecycle                                    │
│  • Owns audit.db (sqlite)                                               │
│  • Calls agent-connect to initiate outbound                             │
└──────────────┬──────────────────────────────────────────────────────────┘
               │ POST /outbound                                 ▲
               ▼                                                │ events
┌─────────────────────────────────────┐          ┌──────────────┴─────────────┐
│          agent-connect              │          │       event-ingestor       │
│  (the TAC application)              │          │  POST /twilio/events       │
│  • Inbound SMS webhook              │◀────────▶│  • Signature validation    │
│  • ConversationRelay WebSocket      │  Twilio  │  • Dedupe on event id      │
│  • Memory recall + Orchestrator     │          │  • Fan out to scheduler    │
│  • Tools (@function_tool)           │          │  • Write audit             │
│  • Outbound conversation creation   │          │                            │
└──────────────┬──────────────────────┘          └────────────────┬───────────┘
               │                                                  │
               ▼                                                  │
      ┌─────────────────┐                                         │
      │     Twilio      │ ◀───────── Event Streams webhook ───────┘
      │ ConversationRelay│
      │ Orchestrator    │
      │ Memory          │
      │ Intelligence    │
      └─────────────────┘

      ┌─────────────────┐          ┌─────────────────┐
      │  test-harness   │          │    wallboard    │
      │  (Vite + React) │          │  (Vite + React) │
      │  Upload jobs,   │          │  Live KPIs,     │
      │  inspect per-   │          │  queue depth,   │
      │  job debug      │          │  recent audit   │
      └────────┬────────┘          └────────┬────────┘
               │                            │
               └────── reads/writes ────────┘
                           │
                           ▼
                       scheduler
```

---

## Services

### `apps/scheduler` — the brain

Owns Jobs, JobRuns, and audit.db. All business policy lives here.

**Responsibilities**
- Accept `POST /jobs` from upstream apps
- Run policy checks before firing:
  - **Time windows** — respect `allowedHoursLocal` in the recipient's timezone (TCPA quiet hours in the US)
  - **Consent** — refuse marketing SMS without a consent record
  - **Do-not-contact** — suppression list check
  - **Dedupe** — don't double-fire the same `(scenario, to)` within a window
  - **Concurrency** — cap in-flight jobs per campaign
- Fire jobs by calling `agent-connect` to initiate outbound (voice or SMS)
- Advance `JobRun` state based on events from `event-ingestor`
- Apply retry/backoff policy
- Apply channel fallback (voice no-answer → SMS)
- Expose read endpoints for the wallboard and test-harness

**Folder layout**
```
scheduler/src/scheduler/
├── main.py              # FastAPI app
├── http/                # routes: /jobs, /jobs/{id}, /runs, /audit
├── jobs/                # queue + JobRun lifecycle
├── policy/              # time-window, consent, dedupe, suppression
├── fallback/            # channel fallback rules
├── outbound/            # calls agent-connect
└── infra/               # db, otel, config
```

### `apps/agent_connect` — the TAC application

The LLM-powered conversation runtime. Uses the `twilio-agent-connect` Python SDK to connect your LLM (OpenAI, Bedrock, Foundry, etc.) to Twilio's channels.

**Responsibilities**
- Inbound SMS webhook (TAC's `SMSChannel`)
- Inbound/outbound voice via ConversationRelay (TAC's `VoiceChannel`)
- Memory retrieval before each response (identity resolution + Recall)
- Orchestrator session management
- Tools exposed via `@function_tool` (lookup account, schedule callback, transfer, etc.)
- Outbound conversation creation on behalf of the scheduler

**Folder layout**
```
agent_connect/src/agent_connect/
├── main.py              # TAC + VoiceChannel + SMSChannel wiring + TACFastAPIServer
├── handlers/            # on_message_ready implementations
├── tools/               # @function_tool definitions
├── prompts/             # system prompts per scenario
└── infra/               # otel, config
```

### `apps/event_ingestor` — the single webhook sink

One place for Twilio Event Streams to land. Validates, dedupes, fans out.

**Responsibilities**
- `POST /twilio/events` — Twilio Event Streams webhook sink
- Validate Twilio signature on every request
- Dedupe on event id (sqlite `seen_events` table)
- Route events:
  - Call/message status, AMD result → scheduler (advance JobRun)
  - Intelligence `OperatorResult` → scheduler (attach to JobRun) + audit
  - Errors → audit + wallboard
- Write every event to audit

**Folder layout**
```
event_ingestor/src/event_ingestor/
├── main.py              # FastAPI app
├── http/                # /twilio/events
├── validation/          # Twilio signature validation
├── routing/             # event → consumer mapping
├── sinks/               # scheduler client, audit writer
└── infra/
```

### `apps/test_harness` — the developer tool

Vite + React. Upload a JSON file of jobs, watch each one execute, inspect everything Twilio produces.

**Per-job panels**
- Status timeline (queued → in-progress → completed/failed)
- ConversationRelay transcript
- SMS thread
- Memory observations recalled + written
- Conversation Intelligence operator results
- OTel trace link

### `apps/wallboard` — the operator view

Vite + React. Read-only live view of system health.

**Panels**
- Queue depth by scenario
- In-flight jobs
- Success / failure rates (last hour, last 24h)
- Recent errors from audit
- Recent Intelligence findings (sentiment shifts, escalation signals)

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

---

## Core concepts

### Job vs JobRun

A **Job** is the business intent — "contact this customer at this time for this reason." It's immutable once accepted.

A **JobRun** is one execution attempt. Retries create new JobRuns against the same Job.

```python
class Job(BaseModel):
    id: str
    direction: Literal['outbound', 'inbound-followup']
    channel: Literal['voice', 'sms']
    to: str                           # E.164
    from_: str | None = None          # which Twilio number; scheduler picks default if None
    scheduled_for: datetime | Literal['now']
    scenario: str                     # key into prompts/ and tools/
    context: dict[str, Any] = {}
    consent: Consent | None = None
    constraints: Constraints | None = None
    retry_policy: RetryPolicy | None = None

class JobRun(BaseModel):
    job_id: str
    attempt: int
    status: Literal['pending', 'queued', 'in-progress', 'completed', 'failed', 'suppressed']
    conversation_id: str | None = None       # Twilio Orchestrator Conversation
    profile_id: str | None = None            # Twilio Memory Profile
    twilio_call_sid: str | None = None
    twilio_message_sid: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    terminal_reason: str | None = None
```

**Note:** `conversation_id` lives on `JobRun`, not `Job`. The Conversation is Twilio-side state created when the Job fires; it's not part of the business intent.

### Vocabulary — avoiding collisions with Twilio

| Our term | What it is | Twilio term we avoid |
|---|---|---|
| **Job** | A unit of outbound work | — (`Task` is TaskRouter) |
| **JobRun** | One execution attempt | — |
| **Scenario** | Named prompt + tool set | — |
| — | — | **Conversation** (Orchestrator) — we store the id in JobRun |
| — | — | **Communication** (one utterance/message inside a Conversation) |

### Tracing vs auditing — different concerns

| | Tracing (OTel) | Auditing |
|---|---|---|
| **Question** | Where did time go? Where did it fail? | Who did what, when? |
| **Storage** | OTel backend (Honeycomb, Tempo, Datadog, App Insights) | `audit.db` sqlite, owned by scheduler |
| **Lifetime** | Short retention, high volume | Long retention, append-only |
| **Writer** | Auto-instrumentation + manual spans | `audit.record(...)` explicit calls |

Both run in every app.

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
| Phone number | Manual (Twilio console) | `scheduler` env (default `from`) |
| Event Streams sink | `scripts/provision.py` | Points at `event-ingestor` public URL |

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

## Production deployment

Single domain, path-based routing via Caddy or nginx:

```
blueprint.example.com/scheduler/*   → scheduler:3001
blueprint.example.com/agent/*       → agent-connect:3002   (HTTP + WS upgrade)
blueprint.example.com/events/*      → event-ingestor:3003
blueprint.example.com/wallboard/*   → wallboard static
blueprint.example.com/harness/*     → test-harness static
blueprint.example.com/              → wallboard
```

Each FastAPI app reads a `BASE_PATH` env var and mounts its routes under it, so the app is self-contained and testable at any mount point.

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

## What this blueprint does *not* include

- Multi-tenant isolation (one Memory Store per customer) — ISV pattern noted in docs
- Durable queue (sqlite is fine for the demo; swap for Postgres + a real queue for prod volumes)
- Authentication on inter-service HTTP (add API keys or mTLS before deploying)
- Full retry semantics for Event Streams (dedupe is in; durable replay is not)
- Horizontal scaling of agent-connect (TAC can scale; the shared conversation history dict in the sample needs externalizing)
- UI auth — test-harness and wallboard are open; add SSO before exposing

Each is called out in `docs/` with a suggested path.

---

## Repository layout

```
voice-blueprint/
├── README.md
├── PROJECT_BRIEF.md          # Short summary — seed for other Claude sessions
├── pyproject.toml            # uv workspace root
├── uv.lock
├── Procfile                  # honcho process definitions
├── ngrok.yml                 # dual-tunnel config
├── Caddyfile.example         # prod routing example
├── .env.example
├── apps/
│   ├── scheduler/
│   ├── agent_connect/
│   ├── event_ingestor/
│   ├── test_harness/         # Vite + React
│   └── wallboard/            # Vite + React
├── shared/
│   └── src/voice_blueprint_shared/
├── examples/
│   └── sample_scenarios/
│       ├── jobs.sample.json
│       ├── prompts/
│       └── tools/
├── scripts/
│   └── provision.py          # creates Memory Store, Orchestrator Config, Intelligence Config, Event Stream sink
└── docs/
    ├── 01-architecture.md
    ├── 02-job-lifecycle.md
    ├── 03-twilio-provisioning.md
    ├── 04-event-streams-setup.md
    └── 05-observability.md
```

---

## Key decisions, recorded

| Decision | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | TAC Python SDK is the more mature of the two; FastAPI + Pydantic is the natural fit |
| Package manager | `uv` | Native workspaces, fast, lockfile |
| Web framework | FastAPI | Async, Pydantic-native, OpenAPI for free |
| Schema | Pydantic v2 | One model serves validation, serialization, OpenAPI, and type hints |
| Inter-service transport | REST + HTTPS | Simple, debuggable; bus later only if needed |
| Audit store | sqlite via scheduler | One owner, queryable by wallboard; extract when volume justifies |
| Event Streams sink | Webhook → event-ingestor | Simpler than Kinesis/EventBridge for a blueprint |
| Wallboard freshness | Polling (2s) | Simpler than SSE; SSE noted as upgrade |
| Twilio IDs | `.env` per environment | Fresh account produces different IDs; no hardcoded TS/py |
| LLM provider | OpenAI (default); Bedrock/Foundry documented | TAC supports all; OpenAI is lowest-friction demo |
