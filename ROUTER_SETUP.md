# Single Domain Router Setup

This document explains how to use the Python router to run all three backend services through a single ngrok domain (instead of three separate ones).

## Why Use the Router?

The original setup requires ngrok **Pro** to create three separate tunnel domains:
- `your-scheduler.ngrok.app` → port 3001
- `your-agent.ngrok.app` → port 3002
- `your-events.ngrok.app` → port 3003

With ngrok **Free**, you can only tunnel one domain at a time. The router solves this by:
1. Running all three backends on their normal ports (3001, 3002, 3003)
2. Running a single router on port 3000
3. Routing requests through a single ngrok tunnel based on path prefixes

## Usage

### Local Development (No ngrok)

```bash
# Terminal 1: Start all services with the router
make dev

# This starts:
# - scheduler on :3001
# - agent-connect on :3002
# - event-ingestor on :3003
# - router on :3000
# - test harness on :5173
# - wallboard on :5174
```

Then access:
- Router health: http://localhost:3000/
- Scheduler: http://localhost:3000/scheduler/...
- Agent-connect: http://localhost:3000/agent-connect/...
- Event-ingestor: http://localhost:3000/event-ingestor/...

Or use the direct backend ports if you prefer (e.g., http://localhost:3001 for scheduler).

### With ngrok Free Account

```bash
# Terminal 1: Start all services with the router
make dev

# Terminal 2: Create a single ngrok tunnel to the router
ngrok http 3000

# You'll get a URL like: https://1234-56-789-10.ngrok.app
# Use this as your public domain for all three services
```

Then update your `.env`:
```bash
TWILIO_VOICE_PUBLIC_DOMAIN=1234-56-789-10.ngrok.app
SCHEDULER_PUBLIC_URL=https://1234-56-789-10.ngrok.app/scheduler
EVENT_INGESTOR_PUBLIC_URL=https://1234-56-789-10.ngrok.app/event-ingestor
```

Update your Twilio webhooks to:
- Voice inbound: `https://1234-56-789-10.ngrok.app/agent-connect/voice/incoming`
- Scheduler callback: `https://1234-56-789-10.ngrok.app/scheduler/status`
- Event Streams sink: `https://1234-56-789-10.ngrok.app/event-ingestor/events`

## How It Works

The router listens on port 3000 and routes requests based on the path prefix:

```
GET https://your-domain.ngrok.app/scheduler/status
  → forwards to http://localhost:3001/status

GET https://your-domain.ngrok.app/agent-connect/voice/incoming
  → forwards to http://localhost:3002/voice/incoming

POST https://your-domain.ngrok.app/event-ingestor/events
  → forwards to http://localhost:3003/events
```

## Routing Rules

1. **Path-based routing (highest priority)**: Check if path starts with `/scheduler`, `/agent-connect`, or `/event-ingestor`
2. **Host header fallback**: Check if Host header contains the service name (e.g., `scheduler.localhost`)
3. **404**: If no match, return 404

## Endpoints

- `GET /` — Router info and available backends
- `GET /health` — Health check
- `/{path}` — Forwards to appropriate backend based on path prefix

## Router Logs

When running with `make dev`, you'll see router logs like:
```
INFO:     Routing GET /scheduler/status -> http://localhost:3001/status
INFO:     Routing POST /agent-connect/voice/incoming -> http://localhost:3002/voice/incoming
```

## Disabling the Router

To go back to using ngrok three-tunnel setup:

1. Edit `Procfile` and remove the `router` line
2. Run `make dev` again
3. Update `.env` to use three separate ngrok domains

## Dependencies

The router requires `httpx` and `fastapi`, which should already be installed via your project's dependencies. If not:

```bash
uv pip install httpx fastapi uvicorn
```

## Troubleshooting

### "Connection refused" errors
- Ensure all three backends (3001, 3002, 3003) are running
- Check that ngrok is tunneling to port 3000, not 3001

### Wrong backend receiving requests
- Verify the path prefix in the URL (e.g., `/scheduler/`, not `/schedulers/`)
- Check router logs to see where requests are being routed

### CORS or header issues
- The router preserves all request headers except `Host`
- If you need custom header handling, update the router code
