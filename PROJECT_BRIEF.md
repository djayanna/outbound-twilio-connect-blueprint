# voice-blueprint — project brief

Drop this into any Claude session as context. It summarizes the goals, architecture, naming conventions, and tech choices so Claude can be productive immediately.

---

## What this is

A reference implementation showing how a customer-facing application uses the Twilio stack to run inbound + outbound voice and SMS conversations driven by an LLM agent, with a scheduler that owns the business logic for when and how to reach out.

Twilio products used: **TAC (Twilio Agent Connect)**, **ConversationRelay**, **Conversation Orchestrator**, **Conversation Memory**, **Conversation Intelligence**, **Event Streams**.

Not customer-specific. One sample scenario set lives under `examples/sample_scenarios/`.

---

## Stack

- **Language**: Python 3.11+
- **Package manager**: `uv` (workspaces)
- **Web framework**: FastAPI (async)
- **Schemas**: Pydantic v2
- **LLM glue**: `twilio-agent-connect` Python SDK
- **DB**: sqlite (audit, dedupe, suppression)
- **Frontend**: Vite + React (two apps: test-harness, wallboard)
- **Process manager (dev)**: honcho + Procfile
- **Tunnels (dev)**: ngrok, dual tunnel
- **Observability**: OpenTelemetry (traces + metrics)
- **Inter-service transport**: REST + HTTPS only — no message bus

---

## Services (apps)

| App | Role | Port |
|---|---|---|
| `scheduler` | Owns Jobs, JobRuns, audit.db. All business policy. Fires outbound by calling agent-connect. | 3001 |
| `agent_connect` | The TAC application. Inbound SMS webhook + ConversationRelay WS + Memory + tools + outbound creation. | 3002 |
| `event_ingestor` | Single webhook sink for Twilio Event Streams. Validates, dedupes, fans out, writes audit. | 3003 |
| `test_harness` | Vite+React dev tool. Upload JSON of jobs, inspect transcript / memory / CI / status per job. | 5173 |
| `wallboard` | Vite+React operator view. Live queue depth, success rates, recent errors and CI findings. | 5174 |

`shared/` is a `uv` workspace package (`voice-blueprint-shared`) imported by every backend app. Contains `job.py` (Pydantic models), `audit.py` (writer), `otel.py` (init helper).

---

## Core concepts

### Job vs JobRun

- **Job** = business intent ("contact this customer at this time for this reason"). Immutable once accepted.
- **JobRun** = one execution attempt. Retries create new JobRuns against the same Job.
- `conversation_id` lives on **JobRun**, not Job — it's Twilio-side state created when the Job fires.

### Job fields

```
id, direction ('outbound' | 'inbound-followup'), channel ('voice' | 'sms'),
to (E.164), from_ (optional), scheduled_for (ISO | 'now'), scenario (str),
context (dict), consent, constraints (allowed_hours_local, do_not_contact_before),
retry_policy
```

### Scheduler policy (what makes it more than cron)

- TCPA quiet hours in **recipient's timezone**
- Consent gate (no marketing SMS without a consent record)
- Do-not-contact suppression
- Dedupe within window on `(scenario, to)`
- Concurrency caps per campaign
- Retry/backoff driven by Event Streams
- Channel fallback (voice no-answer → SMS)

### Vocabulary — stay off Twilio's terms

| Our term | Twilio term we don't reuse |
|---|---|
| Job | — (TaskRouter owns "Task") |
| JobRun | — |
| Scenario | — |
| — | Conversation (Orchestrator) — stored as `JobRun.conversation_id` |
| — | Communication (one utterance/message inside a Conversation) |

### Tracing vs auditing

- **Tracing** = OpenTelemetry spans, cross-service, "where did time go / where did it fail?"
- **Auditing** = append-only business event log in `audit.db` owned by scheduler, "who did what, when?"
- Both run in every app. They are not interchangeable.

---

## Architecture flow

```
upstream app → POST /jobs → scheduler
scheduler → policy check → POST /outbound → agent-connect
agent-connect → Twilio (ConversationRelay or Messages API)
Twilio → Event Streams webhook → event-ingestor
event-ingestor → scheduler (advance JobRun) + audit.db + wallboard metrics
wallboard ← polls scheduler (/jobs, /stats, /audit)
test-harness ← polls scheduler + reads per-job Twilio detail
```

Inbound SMS and voice arrive directly at agent-connect via Twilio webhooks (Orchestrator Configuration routes them). The scheduler is not involved in inbound unless the agent schedules a callback (`direction: 'inbound-followup'`).

---

## Twilio resources

Provisioned once per environment by `scripts/provision.py`, which writes IDs to `.env`:

- Memory Store
- Orchestrator Configuration (linked to Memory Store, grouping `GROUP_BY_PROFILE`)
- Intelligence Configuration (linked to Orchestrator Config)
- Event Streams webhook sink (points at event-ingestor public URL)

Phone number is manual (Twilio Console), its E.164 goes in `.env` as the default `from`.

Never hardcode Twilio IDs — they differ per account.

---

## Repository layout

```
voice-blueprint/
├── README.md
├── PROJECT_BRIEF.md
├── pyproject.toml            # uv workspace root
├── Procfile                  # honcho
├── ngrok.yml
├── .env.example
├── apps/
│   ├── scheduler/            # src/scheduler/{main,http,jobs,policy,fallback,outbound,infra}
│   ├── agent_connect/        # src/agent_connect/{main,handlers,tools,prompts,infra}
│   ├── event_ingestor/       # src/event_ingestor/{main,http,validation,routing,sinks,infra}
│   ├── test_harness/         # Vite + React
│   └── wallboard/            # Vite + React
├── shared/
│   └── src/voice_blueprint_shared/{job,audit,otel}.py
├── examples/
│   └── sample_scenarios/{jobs.sample.json, prompts/, tools/}
├── scripts/provision.py
└── docs/
    ├── 01-architecture.md
    ├── 02-job-lifecycle.md
    ├── 03-twilio-provisioning.md
    ├── 04-event-streams-setup.md
    └── 05-observability.md
```

Python package names use underscores (`agent_connect`, `event_ingestor`); directory names mirror them.

---

## Decisions already locked in

| Topic | Decision |
|---|---|
| Language | Python 3.11+ (not TypeScript) |
| Package manager | `uv` |
| Service transport | REST + HTTPS, no bus |
| Audit storage | sqlite, owned by scheduler, read via scheduler's HTTP API |
| Event Streams sink | Webhook (not Kinesis/EventBridge) |
| Wallboard freshness | Polling, 2s (SSE noted as later upgrade) |
| Routing in prod | Path-based, single domain, Caddy or nginx |
| Twilio IDs | `.env` only, provisioned by `scripts/provision.py` |
| Dispatcher extraction | Scheduler stays one service; extract durable queue only when volume justifies |
| LLM | OpenAI default; Bedrock/Foundry supported via TAC |

---

## Important gotchas (from Twilio skills)

- **Voice double-billing**: don't combine passive VOICE capture rules in Orchestrator Config with active TwiML `<ConversationRelay conversationConfiguration=...>`. Pick one. Blueprint uses active TwiML.
- **Memory Store must exist before Orchestrator Config**: `memory_store_id` is required at Orchestrator Config creation.
- **PUT replaces everything on Orchestrator Config**: always re-fetch before updating; omitted fields are silently deleted.
- **Orchestrator Config grouping type is immutable**: pick `GROUP_BY_PROFILE` at creation; recreate the config to change it.
- **Intelligence v3 PUT creates an inactive version with no activation API**: to update a live Intelligence Config, DELETE and POST to recreate.
- **ConversationRelay fragments TTS**: one agent utterance → multiple `Communications`. Intelligence operators fire per Communication, so cost scales with fragment count.
- **Event Streams delivers at-least-once**: event-ingestor must dedupe on event id. `seen_events` sqlite table.

---

## What this blueprint does *not* do (yet)

- Multi-tenant Memory Stores (ISV pattern noted)
- Durable queue (sqlite is demo-grade)
- Inter-service auth (add API keys / mTLS before deploying)
- UI auth on wallboard / test-harness
- Horizontal scaling of agent-connect (the sample's in-memory conversation history dict needs externalizing)
- Full HIPAA / PCI configuration (noted in `docs/`)

---

## When asked to add or change something, check in this order

1. Does it belong in **scheduler** (business policy, Job lifecycle)?
2. Does it belong in **agent-connect** (LLM conversation, tools, Twilio channel I/O)?
3. Does it belong in **event-ingestor** (Twilio-originated events)?
4. Does it belong in **shared/** (schema shared by 2+ apps, OTel init, audit writer)?
5. If it's a UI concern — is it dev-time (test-harness) or ops-time (wallboard)?

Resist adding a sixth app. Resist adding a message bus. Resist hardcoding Twilio IDs.
