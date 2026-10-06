# Deployment

The quickstart target is "one host + ngrok" and "docker compose on any VM." Everything beyond that reuses the same images.

## Containerized dev

```bash
cp .env.example .env
# fill in TWILIO_* creds and OPENAI_API_KEY
make up          # docker compose up -d --build
```

Services and host-mapped ports:

| Service | Local URL |
|---|---|
| scheduler | http://localhost:3001 |
| agent-connect | http://localhost:3002 |
| event-ingestor | http://localhost:3003 |
| test-harness | http://localhost:5173 |
| wallboard | http://localhost:5174 |

Scheduler + event-ingestor share a `data/` volume for SQLite (audit log is the one both touch).

## Ingress

The repo ships a `Caddyfile.example` showing one way to front everything with a single hostname:

```
blueprint.example.com {
    handle_path /scheduler/* { reverse_proxy localhost:3001 }
    handle_path /agent/*     { reverse_proxy localhost:3002 }
    handle_path /events/*    { reverse_proxy localhost:3003 }
    handle_path /harness/*   { root * /var/www/test_harness; file_server }
    handle /*                { root * /var/www/wallboard; file_server }
}
```

Three public URLs **must** terminate on your ingress regardless of layout:

| Env var | Must reach | Why |
|---|---|---|
| `TWILIO_VOICE_PUBLIC_DOMAIN` | agent-connect (TAC routes) | TwiML, ConversationRelay WS, SMS webhook, call events |
| `SCHEDULER_PUBLIC_URL` | scheduler | per-call `statusCallback` |
| `EVENT_INGESTOR_PUBLIC_URL` | event-ingestor | Event Streams sink |

## Production checklist

- Set `DEV_MODE=0` on every service.
- Set `BLUEPRINT_API_KEY` and share it with upstream clients.
- Set `UPSTREAM_CALLBACK_SIGNING_KEY` and document the HMAC-SHA256 header for your consumers.
- Terminate TLS at the ingress. Twilio refuses HTTP for ConversationRelay WebSocket.
- Point `OTEL_EXPORTER_OTLP_ENDPOINT` at your observability stack.
- Mount `data/` on durable storage. SQLite WAL is fine for a single host; swap in Postgres by implementing the `JobRepository` protocol.

See [04-compliance.md](./04-compliance.md) for TCPA/GDPR/PCI pointers.
