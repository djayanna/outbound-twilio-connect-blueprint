# event-ingestor

Twilio Event Streams webhook sink. One place for all Twilio-originated events.

Run: `uv run uvicorn event_ingestor.main:app --port 3003 --reload`

Routes:
- `POST /twilio/events` — Event Streams sink. Validates signature, dedupes on
  event id (sqlite `seen_events`), writes every event to audit, fans out to the
  scheduler for status-changing events.
- `GET /health`

The ingestor also writes to the same `audit.db` the scheduler owns. In this
blueprint both services share the file; in prod the scheduler would expose a
write endpoint instead.
