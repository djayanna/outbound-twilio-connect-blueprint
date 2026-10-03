# Local setup

Everything you need to clone, boot, and submit the first Job.

## Prerequisites

- **Python 3.11+**
- **uv** — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Node 20+** (for the two Vite UIs)
- **honcho** — `uv tool install honcho`
- **ngrok** (or any public-tunnel tool) — Twilio must reach your laptop for webhooks and ConversationRelay

## One-time setup

```bash
# Copy env defaults
cp .env.example .env
# fill in TWILIO_* creds and OPENAI_API_KEY

# Install Python deps for all workspace members (incl. dev + provision)
uv sync --all-packages --group dev --group provision

# Install JS deps for the two UIs
npm --prefix apps/test_harness install
npm --prefix apps/wallboard install

# Provision Twilio resources + write IDs to .env
uv run python scripts/provision.py

# Start tunnels (one each for agent-connect webhooks and event-ingestor)
ngrok start --all --config ngrok.yml
```

Update `.env` with the two ngrok hostnames:

```
TWILIO_VOICE_PUBLIC_DOMAIN=xxxx.ngrok.app
EVENT_INGESTOR_PUBLIC_URL=https://yyyy.ngrok.app
SCHEDULER_PUBLIC_URL=https://zzzz.ngrok.app
```

## Boot

```bash
make dev   # or: honcho start
```

| Service | URL |
|---|---|
| scheduler | http://localhost:3001 |
| agent-connect | http://localhost:3002 |
| event-ingestor | http://localhost:3003 |
| test-harness | http://localhost:5173 |
| wallboard | http://localhost:5174 |

## Authentication

Every write endpoint on the scheduler is behind `X-Blueprint-Key`. For local dev set `DEV_MODE=1` in your `.env` to bypass; in prod set `BLUEPRINT_API_KEY` and pass it in the header. The test-harness reads `VITE_BLUEPRINT_API_KEY` at build time.

## First job

Open the test harness at http://localhost:5173, upload `examples/jobs.sample.json`, and watch each job land in the call history. Click a row to inspect the Job, its JobRuns, and the audit trail. Twilio status callbacks will advance each run from `queued` → `in-progress` → `completed`.

## Troubleshooting

See [05-troubleshooting.md](./05-troubleshooting.md).
