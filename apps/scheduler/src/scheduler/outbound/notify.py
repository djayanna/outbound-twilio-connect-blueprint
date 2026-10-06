"""audit + upstream_callback together.

Keeps every "a thing happened to this Job/Run" write in one place so new
call sites don't forget to invoke every sink.

Scheduler owns its own audit log; event-ingestor owns Twilio events. The
two logs are intentionally separate — a mirror hop was tried early and
produced duplicate rows when both services shared the audit DB file
(default in `honcho start` and in docker compose). Add it back only when
the two services have genuinely distinct storage.
"""
from __future__ import annotations

import sqlite3

from voice_blueprint_shared.audit import AuditEvent, audit_record
from voice_blueprint_shared.job import Job

from scheduler.outbound.upstream import notify_upstream


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


__all__ = ["record_and_notify"]
