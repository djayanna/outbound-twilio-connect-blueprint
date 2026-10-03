"""Firing loop.

A single asyncio.Task started from the scheduler's lifespan. Each tick:

  1. Promote `scheduled` jobs whose scheduled_for has passed to `firing`.
  2. For every `firing` job with no live JobRun, create a JobRun(attempt=1,
     status="queued"), POST the Job to agent-connect, record the returned
     Twilio SID on the run.
  3. Twilio StatusCallbacks (added in T1.3) drive queued → in-progress →
     completed from here on.

Failures to reach agent-connect mark the run `failed` with the exception as
`terminal_reason` so retry policy in T2.1 has something to inspect.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from voice_blueprint_shared.audit import AuditEvent, audit_record
from voice_blueprint_shared.job import Job, JobRun

from scheduler.jobs.store import JobStore
from scheduler.outbound.agent_client import initiate_outbound

log = logging.getLogger("scheduler.worker")

TICK_SECONDS = 1.0

# Injected for tests. In production the module's own `initiate_outbound` is used.
AgentCaller = Callable[[Job], Awaitable[dict]]


async def run_loop(
    store: JobStore,
    audit_db: sqlite3.Connection,
    agent_caller: AgentCaller | None = None,
    stop_event: asyncio.Event | None = None,
    tick_seconds: float = TICK_SECONDS,
) -> None:
    """Drain `firing` jobs forever. Returns when stop_event is set."""
    caller = agent_caller or initiate_outbound
    stop = stop_event or asyncio.Event()
    while not stop.is_set():
        try:
            await _tick(store, audit_db, caller)
        except Exception:  # pragma: no cover — a bad tick must not kill the loop
            log.exception("worker tick failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=tick_seconds)


async def _tick(store: JobStore, audit_db: sqlite3.Connection, caller: AgentCaller) -> None:
    now = datetime.now(UTC)

    for job in store.list_jobs(status="scheduled"):
        if _is_due(job, now):
            job.status = "firing"
            store.put_job(job)

    for job in store.list_jobs(status="firing"):
        if _has_live_run(store, job):
            continue
        await _fire(job, store, audit_db, caller)


def _is_due(job: Job, now: datetime) -> bool:
    if job.scheduled_for == "now":
        return True
    due = job.scheduled_for
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    return due <= now


def _has_live_run(store: JobStore, job: Job) -> bool:
    return any(r.status in ("queued", "in-progress") for r in store.runs_for(job.id))


async def _fire(
    job: Job, store: JobStore, audit_db: sqlite3.Connection, caller: AgentCaller
) -> None:
    attempt = len(store.runs_for(job.id)) + 1
    run = JobRun(job_id=job.id, attempt=attempt, status="queued")
    store.put_run(run)
    audit_record(
        audit_db,
        AuditEvent(
            actor="scheduler",
            action="run.queued",
            subject=job.id,
            data={"attempt": attempt, "channel": job.channel},
        ),
    )

    try:
        result = await caller(job)
    except Exception as exc:
        run.status = "failed"
        run.terminal_reason = f"agent_connect_error:{type(exc).__name__}"
        run.ended_at = datetime.now(UTC)
        store.put_run(run)
        audit_record(
            audit_db,
            AuditEvent(
                actor="scheduler",
                action="run.failed",
                subject=job.id,
                data={"attempt": attempt, "reason": run.terminal_reason},
            ),
        )
        log.warning("fire failed for job %s: %s", job.id, exc)
        return

    run.twilio_call_sid = result.get("twilio_call_sid")
    run.twilio_message_sid = result.get("twilio_message_sid")
    run.started_at = datetime.now(UTC)
    store.put_run(run)
    audit_record(
        audit_db,
        AuditEvent(
            actor="scheduler",
            action="run.dispatched",
            subject=job.id,
            data={
                "attempt": attempt,
                "twilio_call_sid": run.twilio_call_sid,
                "twilio_message_sid": run.twilio_message_sid,
            },
        ),
    )


__all__ = ["run_loop", "TICK_SECONDS"]
