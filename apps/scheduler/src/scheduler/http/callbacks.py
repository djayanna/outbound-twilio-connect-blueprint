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


@router.post("/twilio/amd")
async def twilio_amd(req: Request):
    """Async AMD callback from Twilio — "who answered?".

    Twilio runs machine detection in parallel with TwiML execution and POSTs
    the verdict here. If the answerer is a human, we do nothing (the
    ConversationRelay session is already live). Otherwise we consult the
    Job's `context.on_machine_answer` policy:

      * "hangup" (default)       — REST-hang up the call, fail the run with
                                   terminal_reason=voicemail. The channel-
                                   fallback rule already maps voicemail → SMS.
      * "leave_voicemail"        — leave the call connected and tag the run
                                   so the LLM session knows to leave a short
                                   message (wired in a follow-up commit).
    """
    body = await req.body()
    form = dict((await req.form()).multi_items())
    _verify_twilio_signature(req, body, form)

    sid = form.get("CallSid")
    answered_by = form.get("AnsweredBy") or ""
    if not sid:
        raise HTTPException(status_code=400, detail="missing CallSid")

    _apply_amd(sid, answered_by, req.app.state.store, req.app.state.audit_db)
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


# AnsweredBy values Twilio returns on the AMD callback — see
# https://www.twilio.com/docs/voice/answering-machine-detection
_HUMAN_ANSWERS = {"human", "unknown"}  # unknown = AMD timed out; treat as human
_MACHINE_ANSWERS = {
    "machine_start",
    "machine_end_beep",
    "machine_end_silence",
    "machine_end_other",
    "fax",
}


def _apply_amd(sid: str, answered_by: str, store: JobStore, audit_db) -> None:
    run = store.run_by_twilio_sid(sid)
    if not run:
        audit_record(
            audit_db,
            AuditEvent(actor="twilio-amd", action="run.unmatched", subject=sid,
                       data={"answered_by": answered_by}),
        )
        return
    job = store.get_job(run.job_id)

    # Record the verdict on the run so agent-connect can pick it up before
    # the first LLM turn (via GET /runs/by-sid/{sid}).
    run.answered_by = answered_by
    store.put_run(run)

    record_and_notify(
        audit_db,
        actor="twilio-amd",
        action="run.amd",
        job=job,
        subject=run.job_id,
        data={"attempt": run.attempt, "sid": sid, "answered_by": answered_by},
    )

    if answered_by in _HUMAN_ANSWERS or job is None:
        return
    if answered_by not in _MACHINE_ANSWERS:
        return  # unknown bucket — be conservative, do nothing

    policy = (job.context or {}).get("on_machine_answer", "hangup")
    if policy == "hangup":
        _hangup_and_fail(sid, run, job, store, audit_db, reason="voicemail")
    # "leave_voicemail" leaves the CR session connected; agent-connect's
    # on_message_ready reads run.answered_by + job.context on the first
    # turn and switches the system prompt to a voicemail persona.


def _hangup_and_fail(
    sid: str, run: JobRun, job, store: JobStore, audit_db, reason: str,
) -> None:
    """Hang up the Twilio call out-of-band and mark the run failed."""
    try:
        from twilio.rest import Client

        Client(settings.account_sid, settings.auth_token).calls(sid).update(
            status="completed"
        )
    except Exception as exc:  # best-effort; the run.failed audit still fires
        audit_record(
            audit_db,
            AuditEvent(actor="scheduler", action="run.hangup_failed",
                       subject=run.job_id,
                       data={"sid": sid, "error": str(exc)}),
        )

    run.status = "failed"
    run.terminal_reason = reason
    run.ended_at = _now()
    store.put_run(run)
    record_and_notify(
        audit_db,
        actor="scheduler",
        action="run.failed",
        job=job,
        subject=run.job_id,
        data={"attempt": run.attempt, "sid": sid, "terminal_reason": reason},
    )
    _maybe_retry(job, run, reason, store, audit_db)


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
