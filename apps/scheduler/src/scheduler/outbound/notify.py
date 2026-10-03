"""audit + upstream_callback together.

Keeps every "a thing happened to this Job/Run" write in one place so new
call sites don't forget to invoke the upstream hook.
"""
from __future__ import annotations

import sqlite3

from voice_blueprint_shared.audit import AuditEvent, audit_record
from voice_blueprint_shared.job import Job

from scheduler.jobs.store import JobStore
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


def record_and_notify_by_id(
    audit_db: sqlite3.Connection,
    store: JobStore,
    actor: str,
    action: str,
    job_id: str,
    data: dict,
) -> None:
    record_and_notify(audit_db, actor, action, store.get_job(job_id), job_id, data)


__all__ = ["record_and_notify", "record_and_notify_by_id"]
