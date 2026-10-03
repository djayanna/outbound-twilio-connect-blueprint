"""audit + upstream_callback + event-ingestor fan-out, together.

Keeps every "a thing happened to this Job/Run" write in one place so new
call sites don't forget to invoke every sink.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from datetime import UTC, datetime

import httpx
from voice_blueprint_shared.audit import AuditEvent, audit_record
from voice_blueprint_shared.job import Job

from scheduler.config import settings
from scheduler.outbound.upstream import notify_upstream

_log = logging.getLogger("scheduler.notify")


def record_and_notify(
    audit_db: sqlite3.Connection,
    actor: str,
    action: str,
    job: Job | None,
    subject: str,
    data: dict,
) -> None:
    audit_record(
        audit_db,
        AuditEvent(actor=actor, action=action, subject=subject, data=data),
    )
    if job is not None:
        notify_upstream(job, action, data)
    _mirror_to_event_ingestor(actor, action, subject, data)


def _mirror_to_event_ingestor(actor: str, action: str, subject: str, data: dict) -> None:
    """Best-effort POST to event-ingestor so the single-event-store story holds."""
    url = settings.event_ingestor_url
    if not url:
        return
    body = {
        "at": datetime.now(UTC).isoformat(),
        "actor": actor,
        "action": action,
        "subject": subject,
        "data": data,
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        with contextlib.suppress(Exception):
            asyncio.run(_post_lifecycle(url, body))
        return
    loop.create_task(_post_lifecycle(url, body), name="scheduler-lifecycle")


async def _post_lifecycle(url: str, body: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{url.rstrip('/')}/scheduler/lifecycle", json=body)
    except httpx.HTTPError as exc:
        _log.debug("event-ingestor mirror failed: %s", exc)


__all__ = ["record_and_notify"]
