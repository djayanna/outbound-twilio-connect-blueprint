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

from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Request
from twilio.request_validator import RequestValidator
from voice_blueprint_shared.audit import AuditEvent, audit_record

from scheduler.config import settings
from scheduler.conversations.bus import ConversationBus
from scheduler.conversations.repository import ConversationStore

router = APIRouter()


def _conversations(req: Request) -> ConversationStore:
    return req.app.state.conversations


def _bus(req: Request) -> ConversationBus:
    return req.app.state.conversation_bus


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
    else:
        # Notify connected wallboards. The delta is a hint, not the payload —
        # clients refetch from the local-DB read endpoints.
        _bus(req).publish({"type": event_type, "conversation_id": conv_id})
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
    """Validate the Orchestrator webhook's X-Twilio-Signature.

    Conversation Orchestrator signs its JSON webhooks the standard Twilio way
    for JSON bodies: it appends a ``bodySHA256`` query param and signs the full
    URL. RequestValidator re-hashes the raw body, compares it to that param,
    then checks the signature over the URL. So we must pass the *raw body
    string* as params — not an empty string (that was the earlier bug, which
    401'd every real webhook), and not the parsed form (this isn't form-encoded).

    The URL is rebuilt from X-Forwarded-* headers because behind the ngrok
    tunnel ``req.url`` reports the internal http://host, not the public https://
    URL Twilio actually signed.

    Dev bypass only when DEV_MODE=1 and no auth token is set, so prod can't
    silently skip the check.
    """
    sig = req.headers.get("X-Twilio-Signature")
    token = settings.auth_token
    if not token:
        if settings.dev_mode:
            return
        raise HTTPException(status_code=500, detail="auth token not configured")
    if not sig:
        raise HTTPException(status_code=401, detail="missing signature")
    url = _signed_url(req)
    # A genuine Orchestrator JSON webhook always carries bodySHA256. Without it
    # RequestValidator can't hash the body and would raise TypeError on a str
    # body, so fail closed rather than crash.
    if "bodySHA256" not in parse_qs(urlsplit(url).query):
        raise HTTPException(status_code=401, detail="invalid signature")
    validator = RequestValidator(token)
    if not validator.validate(url, body.decode("utf-8"), sig):
        raise HTTPException(status_code=401, detail="invalid signature")


def _signed_url(req: Request) -> str:
    """Reconstruct the public URL Twilio signed, honoring proxy headers.

    ngrok (and most reverse proxies) forward the original scheme/host in
    X-Forwarded-Proto / X-Forwarded-Host; the raw request sees the internal
    hop. Twilio computed the signature over the public URL, so we must too.
    Comma-separated values (multi-proxy chains) take the first entry.
    """
    proto = (req.headers.get("x-forwarded-proto") or req.url.scheme).split(",")[0].strip()
    host = (
        req.headers.get("x-forwarded-host")
        or req.headers.get("host")
        or req.url.netloc
    ).split(",")[0].strip()
    url = f"{proto}://{host}{req.url.path}"
    return f"{url}?{req.url.query}" if req.url.query else url


__all__ = ["router"]
