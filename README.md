# outbound-twilio-connect-blueprint

A reference implementation showing how a customer-facing application can use the Twilio stack — **TAC (Twilio Agent Connect)**, **ConversationRelay**, **Conversation Orchestrator**, **Conversation Memory**, **Conversation Intelligence**, and **Event Streams** — to run outbound voice + SMS conversations powered by an AI agent.

It sits between your system of record (EHR, OMS, CRM) and Twilio. Your systems decide *who* to reach, *why*, and under what rules — timezone, quiet hours, consent, retry budget, channel preference. This layer *enforces* those rules, runs the conversation across voice and SMS, and reports every outcome back so the record of truth stays in your systems.

A test harness exercises the flow for developers; a wallboard surfaces live state for operators. Built in Python with FastAPI, with two Vite + React frontends. Monorepo managed by `uv`.

## Quickstart

```bash
cp .env.example .env             # fill in TWILIO_* + OPENAI_API_KEY
make provision                   # creates Twilio resources, writes IDs to .env
make dev                         # honcho start — five services on 3001–3003 + 5173–5174
```

Open http://localhost:5173, upload `examples/jobs.sample.json`, watch the call history fill in.

For containers:

```bash
make up                          # docker compose up -d --build
```

## Docs

- [`docs/00-overview.md`](docs/00-overview.md) — architecture + request lifecycle
- [`docs/01-local-setup.md`](docs/01-local-setup.md) — clone to first Job
- [`docs/02-twilio-provisioning.md`](docs/02-twilio-provisioning.md) — what the provision script does (Memory, Orchestrator, Intelligence, Event Streams sink + subscription)
- [`docs/03-deployment.md`](docs/03-deployment.md) — Docker / ingress / prod checklist
- [`docs/04-compliance.md`](docs/04-compliance.md) — TCPA, consent, DNC, PCI, HIPAA
- [`docs/05-troubleshooting.md`](docs/05-troubleshooting.md) — common failure modes

## Running tests

```bash
make test                        # ruff + pytest with the 80% coverage gate
```

## Why you'd build this

Most businesses have systems of record that know *when* a customer needs to be contacted — the EHR knows tomorrow's appointments, the OMS knows which package is 20 minutes out, the growth database knows which users haven't opened the app in three weeks — but those systems weren't designed to run the actual conversation. A cron job that fires SMS from inside the CRM is enough until the first time it texts someone at 2 a.m., skips a time zone, double-dials on a retry, or has no record of whether the customer actually heard back.

Some use cases this blueprint is shaped around:

- Healthcare appointment confirmations and reminders
- Last-mile delivery communications
- Re-engaging quiet users (abandoned carts, lapsed subscriptions, dormant trials)
- Payment reminders and collections outreach
- Service outage or incident notifications with two-way acknowledgement

## A broker for conversations

| Message queue | This blueprint |
|---|---|
| Producer publishes a message | Upstream app `POST /jobs` |
| Broker holds and routes work | Scheduler holds `Job`s, applies policy, picks the moment to fire |
| Delivery rules (retry, DLQ, ordering) | Quiet hours, consent, retries, channel fallback, dedupe, concurrency |
| Consumer processes the message | Agent-connect runs the LLM conversation over Twilio |
| Ack / nack back to producer | `upstream_callback_url` POSTs on each Job lifecycle event (HMAC-signed) |
| Dead-letter queue | `JobRun.status = failed` with `terminal_reason`, surfaced in audit + wallboard |

## License

MIT (see `LICENSE`).
