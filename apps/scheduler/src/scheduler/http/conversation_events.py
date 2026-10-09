"""Conversation Orchestrator webhook ingest.

Twilio's Orchestrator POSTs a JSON webhook to the URL(s) in a Configuration's
`statusCallbacks` whenever a conversation, participant, or communication
changes. `scripts/provision.py` registers this scheduler endpoint alongside
agent-connect's `/webhook`, so both receive the stream.

Payload shape (see twilio-conversation-orchestrator skill → Webhooks):

    {"eventType": "COMMUNICATION_CREATED", "timestamp": "...", "data": {...}}

`data` is a Conversation, Participant, or Communication resource depending on
`eventType`. We upsert it into the local mirror (`ConversationStore`) so the
wallboard can render a transcript without polling Twilio's REST API.

Signature validation reuses the JSON-webhook scheme the event-ingestor sink
uses — HMAC-SHA1 over the URL alone, body excluded. If the first live payload
proves the Orchestrator signs differently, adjust `_verify_signature`; the
`DEV_MODE` bypass keeps local development working regardless.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from twilio.request_validator import RequestValidator
from voice_blueprint_shared.audit import AuditEvent, audit_record

from scheduler.config import settings
from scheduler.conversations.repository import ConversationStore

router = APIRouter()


def _conversations(req: Request) -> ConversationStore:
    return req.app.state.conversations


@router.post("/twilio/conversation-events")
async def conversation_event(req: Request):
    """Twilio-signed JSON POST. Mirrors one Orchestrator resource per call."""
    body = await req.body()
    _verify_signature(req, body)

    event = await req.json()
    event_type = event.get("eventType", "")
    data = event.get("data") or {}

    store = _conversations(req)
    conv_id = _dispatch(store, event_type, data)

    if conv_id is None:
        audit_record(
            req.app.state.audit_db,
            AuditEvent(
                actor="orchestrator",
                action="conversation.unhandled",
                subject=event_type or "unknown",
                data={"event_type": event_type},
            ),
        )
    return {"ok": True}


def _dispatch(store: ConversationStore, event_type: str, data: dict) -> str | None:
    """Route an eventType to the matching store upsert. Returns the conversation id."""
    if event_type in ("CONVERSATION_CREATED", "CONVERSATION_UPDATED"):
        return store.upsert_conversation(data)
    if event_type in ("PARTICIPANT_ADDED", "PARTICIPANT_UPDATED"):
        return store.upsert_participant(data)
    if event_type == "PARTICIPANT_REMOVED":
        return store.remove_participant(data)
    if event_type in ("COMMUNICATION_CREATED", "COMMUNICATION_UPDATED"):
        return store.upsert_communication(data)
    return None


def _verify_signature(req: Request, body: bytes) -> None:
    """JSON webhook signing: HMAC-SHA1 over the URL alone (body excluded).

    Matches `event_ingestor.validation`. Dev bypass only when DEV_MODE=1 and
    no auth token is set, so prod can't silently skip the check.
    """
    sig = req.headers.get("X-Twilio-Signature")
    token = settings.auth_token
    if not token:
        if settings.dev_mode:
            return
        raise HTTPException(status_code=500, detail="auth token not configured")
    if not sig:
        raise HTTPException(status_code=401, detail="missing signature")
    validator = RequestValidator(token)
    if not validator.validate(str(req.url), "", sig):
        raise HTTPException(status_code=401, detail="invalid signature")


__all__ = ["router"]
