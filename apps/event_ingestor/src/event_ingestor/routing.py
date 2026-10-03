"""Event routing.

Twilio Event Streams delivers events keyed by `type` (reverse-DNS format
like `com.twilio.voice.call.status-changed`). The ingestor audits every
accepted event; this module decides what *else* to do with it:

  * voice.call.* / messaging.message.*
      → forward to scheduler so run state transitions.
  * intelligence.operator-result.*
      → forward as well — scheduler attaches operator results to the
        matching JobRun (via /internal/events).
  * conversations.memory.*
      → audit only. Not state-changing on our side.

Unknown types are ignored (still audited at the main.py level).
"""
import contextlib

import httpx

from event_ingestor.config import settings

_FORWARD_PREFIXES = (
    "com.twilio.voice.call",
    "com.twilio.messaging.message",
    "com.twilio.intelligence.operator-result",
)


async def route_event(ev: dict) -> None:
    event_type = ev.get("type", "")
    if any(event_type.startswith(p) for p in _FORWARD_PREFIXES):
        await _notify_scheduler(ev)


async def _notify_scheduler(ev: dict) -> None:
    # Scheduler notification is best-effort — audit still captures the event
    # whether or not the scheduler is reachable.
    headers = {}
    if settings.scheduler_api_key:
        headers["X-Blueprint-Key"] = settings.scheduler_api_key
    async with httpx.AsyncClient(timeout=10) as client, contextlib.suppress(httpx.HTTPError):
        await client.post(f"{settings.scheduler_url}/internal/events", json=ev, headers=headers)
