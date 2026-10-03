"""Twilio StatusCallback handler + event-ingestor fan-in.

Twilio posts form-encoded CallStatus / MessageStatus to `/twilio/status`,
signed with X-Twilio-Signature over the full URL + sorted body params.
Event-ingestor forwards Event Streams events to `/internal/events` as JSON
(authenticated via shared-secret header in Tier 3).

Both endpoints transition the matching JobRun in-place and append an audit
entry so the wallboard sees the state change.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from twilio.request_validator import RequestValidator
from voice_blueprint_shared.audit import AuditEvent, audit_record
from voice_blueprint_shared.job import JobRun

from scheduler.config import settings
from scheduler.fallback.channel import next_channel
from scheduler.http.auth import require_api_key
from scheduler.jobs.retry import next_attempt
from scheduler.jobs.store import JobStore
from scheduler.outbound.notify import record_and_notify

router = APIRouter()


def _store(req: Request) -> JobStore:
    return req.app.state.store


@router.post("/twilio/status")
async def twilio_status(req: Request):
    """Twilio-signed form POST. Maps CallSid/MessageSid → JobRun state."""
    body = await req.body()
    form = dict((await req.form()).multi_items())
    _verify_twilio_signature(req, body, form)

    sid = form.get("CallSid") or form.get("MessageSid")
    status = form.get("CallStatus") or form.get("MessageStatus")
    if not sid or not status:
        raise HTTPException(status_code=400, detail="missing CallSid/MessageSid or status")

    _apply_status(sid, status, req.app.state.store, req.app.state.audit_db, source="twilio")
    return {"ok": True}


@router.post("/internal/events", dependencies=[Depends(require_api_key)])
async def internal_event(req: Request):
    """JSON event fan-in from event-ingestor. Loosely-typed by design."""
    ev = await req.json()
    event_type = ev.get("type", "")
    payload = ev.get("payload") or ev.get("data") or {}
    sid = payload.get("CallSid") or payload.get("MessageSid") or ev.get("sid")
    status = payload.get("CallStatus") or payload.get("MessageStatus")
    if sid and status:
        _apply_status(sid, status, req.app.state.store, req.app.state.audit_db, source="events")
    else:
        audit_record(
            req.app.state.audit_db,
            AuditEvent(
                actor="event-ingestor",
                action=event_type or "event.unmatched",
                subject=sid or "unknown",
                data=ev,
            ),
        )
    return {"ok": True}


def _verify_twilio_signature(req: Request, body: bytes, form: dict) -> None:
    """Twilio webhook signing: HMAC-SHA1 over URL + sorted form param pairs."""
    sig = req.headers.get("X-Twilio-Signature")
    token = settings.auth_token
    if not token:
        if not settings.dev_mode:
            raise HTTPException(status_code=500, detail="auth token not configured")
        return  # dev bypass
    if not sig:
        raise HTTPException(status_code=401, detail="missing signature")
    validator = RequestValidator(token)
    if not validator.validate(str(req.url), form, sig):
        raise HTTPException(status_code=401, detail="invalid signature")


def _apply_status(sid: str, raw_status: str, store: JobStore, audit_db, source: str) -> None:
    run = store.run_by_twilio_sid(sid)
    if not run:
        audit_record(
            audit_db,
            AuditEvent(
                actor=source,
                action="run.unmatched",
                subject=sid,
                data={"status": raw_status},
            ),
        )
        return

    new_status, terminal_reason = _translate_status(raw_status)
    if new_status == run.status and terminal_reason is None:
        return  # Twilio delivers duplicates; don't audit no-ops.

    run.status = new_status
    if terminal_reason:
        run.terminal_reason = terminal_reason
    if new_status in ("completed", "failed"):
        run.ended_at = _now()
    elif run.started_at is None and new_status == "in-progress":
        run.started_at = _now()

    store.put_run(run)
    job = store.get_job(run.job_id)
    record_and_notify(
        audit_db,
        actor=source,
        action=f"run.{new_status}",
        job=job,
        subject=run.job_id,
        data={
            "attempt": run.attempt,
            "sid": sid,
            "twilio_status": raw_status,
            "terminal_reason": terminal_reason,
        },
    )

    if new_status == "failed" and job is not None:
        _maybe_retry(job, run, terminal_reason, store, audit_db)


def _maybe_retry(
    job, run: JobRun, terminal_reason: str | None, store: JobStore, audit_db
) -> None:
    """Enqueue a next attempt (optionally on a different channel) if policy allows."""
    nxt = next_attempt(job, run)
    if nxt is None:
        record_and_notify(
            audit_db,
            actor="scheduler",
            action="job.exhausted",
            job=job,
            subject=job.id,
            data={"attempts": run.attempt, "terminal_reason": terminal_reason},
        )
        return

    swap = next_channel(job, terminal_reason)
    if swap and swap != job.channel:
        job.channel = swap
        record_and_notify(
            audit_db,
            actor="scheduler",
            action="job.channel_fallback",
            job=job,
            subject=job.id,
            data={"from": run.attempt, "to_channel": swap, "reason": terminal_reason},
        )

    # Promote back to firing — the worker loop picks it up next tick and
    # dispatches the new attempt.
    job.status = "firing"
    store.put_job(job)
    store.put_run(nxt)
    record_and_notify(
        audit_db,
        actor="scheduler",
        action="run.retry_scheduled",
        job=job,
        subject=job.id,
        data={"attempt": nxt.attempt, "channel": job.channel},
    )


# Twilio CallStatus/MessageStatus → our RunStatus + terminal_reason (if any).
_STATUS_MAP: dict[str, tuple[str, str | None]] = {
    # Voice
    "initiated":    ("queued", None),
    "queued":       ("queued", None),
    "ringing":      ("in-progress", None),
    "in-progress":  ("in-progress", None),
    "answered":     ("in-progress", None),
    "completed":    ("completed", None),
    "busy":         ("failed", "busy"),
    "no-answer":    ("failed", "no-answer"),
    "failed":       ("failed", "failed"),
    "canceled":     ("failed", "canceled"),
    # SMS
    "accepted":     ("queued", None),
    "scheduled":    ("queued", None),
    "sending":      ("in-progress", None),
    "sent":         ("in-progress", None),
    "delivered":    ("completed", None),
    "undelivered":  ("failed", "undelivered"),
    "read":         ("completed", None),
}


def _translate_status(raw: str) -> tuple[str, str | None]:
    return _STATUS_MAP.get(raw, ("in-progress", None))


def _now() -> datetime:
    return datetime.now(UTC)


# Satisfy ruff by exposing JobRun (keeps the type import honest in callers' editors).
__all__ = ["router", "JobRun"]
