import contextlib

import httpx

from event_ingestor.config import settings

# event-type → handler
# TODO: expand as we wire specific event schemas


async def route_event(ev: dict) -> None:
    event_type = ev.get("type", "")
    if event_type.startswith("com.twilio.voice.call") or event_type.startswith(
        "com.twilio.messaging.message"
    ):
        await _notify_scheduler(ev)


async def _notify_scheduler(ev: dict) -> None:
    # Scheduler notification is best-effort — audit still captures the event
    # whether or not the scheduler is reachable.
    async with httpx.AsyncClient(timeout=10) as client, contextlib.suppress(httpx.HTTPError):
        await client.post(f"{settings.scheduler_url}/internal/events", json=ev)
