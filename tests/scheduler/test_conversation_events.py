"""Conversation Orchestrator webhook ingest → ConversationStore mirror.

Exercised via the FastAPI TestClient so the signature dev-bypass (DEV_MODE=1,
no auth token — set in conftest's temp_dbs) and the app.state wiring are
covered end-to-end, not just the store in isolation.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(_reload_settings):
    with patch(
        "scheduler.worker.loop.initiate_outbound",
        AsyncMock(return_value={"twilio_message_sid": "SM_test"}),
    ):
        from scheduler.main import app
        with TestClient(app) as c:
            yield c


def _event(event_type: str, data: dict) -> dict:
    return {"eventType": event_type, "timestamp": "2026-10-09T07:06:09Z", "data": data}


def _post(client, event_type, data):
    return client.post("/twilio/conversation-events", json=_event(event_type, data))


def test_conversation_created_is_listed(client):
    r = _post(client, "CONVERSATION_CREATED", {
        "id": "CO1", "status": "ACTIVE", "createdAt": "2026-10-09T07:06:00Z",
    })
    assert r.status_code == 200

    convs = client.get("/conversations").json()["conversations"]
    assert [c["id"] for c in convs] == ["CO1"]
    assert convs[0]["status"] == "ACTIVE"


def test_participant_and_communication_flow(client):
    _post(client, "CONVERSATION_CREATED", {"id": "CO2", "status": "ACTIVE"})
    _post(client, "PARTICIPANT_ADDED", {
        "id": "PA1", "conversationId": "CO2", "type": "CUSTOMER",
        "addresses": [{"address": "+14434336497", "channel": "SMS"}],
    })
    _post(client, "COMMUNICATION_CREATED", {
        "id": "CM1", "conversationId": "CO2",
        "author": {"address": "+14434336497", "channel": "SMS", "participantId": "PA1"},
        "content": {"type": "TRANSCRIPTION", "text": "I'd like to cancel it."},
        "occurredAt": "2026-10-09T07:06:18Z",
    })

    comms = client.get("/conversations/CO2/communications").json()["communications"]
    assert len(comms) == 1
    assert comms[0]["text"] == "I'd like to cancel it."
    assert comms[0]["author_address"] == "+14434336497"
    assert comms[0]["participant_id"] == "PA1"

    convs = {c["id"]: c for c in client.get("/conversations").json()["conversations"]}
    assert convs["CO2"]["participants"][0]["type"] == "CUSTOMER"


def test_communication_before_conversation_creates_stub(client):
    """Webhooks can arrive out of order; a comm must not be dropped."""
    _post(client, "COMMUNICATION_CREATED", {
        "id": "CM9", "conversationId": "CO9",
        "author": {"address": "+18779213383", "channel": "VOICE"},
        "content": {"text": "Hi, this is an automated reminder."},
        "occurredAt": "2026-10-09T07:06:09Z",
    })
    convs = client.get("/conversations").json()["conversations"]
    assert "CO9" in [c["id"] for c in convs]
    comms = client.get("/conversations/CO9/communications").json()["communications"]
    assert comms[0]["text"] == "Hi, this is an automated reminder."


def test_communication_upsert_is_idempotent(client):
    """Twilio can resend; the same communication id must not duplicate."""
    data = {
        "id": "CM5", "conversationId": "CO5",
        "author": {"address": "+18779213383", "channel": "VOICE"},
        "content": {"text": "October 5 at 3PM."},
        "occurredAt": "2026-10-09T07:06:13Z",
    }
    _post(client, "COMMUNICATION_CREATED", data)
    _post(client, "COMMUNICATION_UPDATED", {**data, "content": {"text": "October 5 at 3PM. Confirmed."}})

    comms = client.get("/conversations/CO5/communications").json()["communications"]
    assert len(comms) == 1
    assert comms[0]["text"] == "October 5 at 3PM. Confirmed."


def test_participant_removed(client):
    _post(client, "CONVERSATION_CREATED", {"id": "CO7", "status": "ACTIVE"})
    _post(client, "PARTICIPANT_ADDED", {
        "id": "PA7", "conversationId": "CO7", "type": "AI_AGENT",
        "addresses": [{"address": "+18779213383", "channel": "VOICE"}],
    })
    _post(client, "PARTICIPANT_REMOVED", {"id": "PA7", "conversationId": "CO7"})

    convs = {c["id"]: c for c in client.get("/conversations").json()["conversations"]}
    assert convs["CO7"]["participants"] == []


def test_unhandled_event_type_is_accepted(client):
    r = _post(client, "SOMETHING_ELSE", {"id": "x"})
    assert r.status_code == 200
    assert client.get("/conversations").json()["conversations"] == []


# ── signature validation (production path, auth token set) ─────────────────
# Orchestrator signs JSON webhooks with a bodySHA256 query param + a signature
# over the full URL. The earlier bug passed "" as the body, so RequestValidator
# couldn't match the body hash and every real webhook 401'd. These lock in the
# correct scheme.
_TOKEN = "secret_token"


@pytest.fixture()
def signed_client(temp_dbs, monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", _TOKEN)
    monkeypatch.setenv("DEV_MODE", "0")
    import importlib
    import sys

    for name in list(sys.modules):
        if name == "scheduler" or name.startswith("scheduler."):
            del sys.modules[name]
    with patch(
        "scheduler.worker.loop.initiate_outbound",
        AsyncMock(return_value={"twilio_message_sid": "SM_test"}),
    ):
        from scheduler.main import app
        with TestClient(app) as c:
            yield c
    for name in list(sys.modules):
        if name == "scheduler" or name.startswith("scheduler."):
            del sys.modules[name]
    _ = importlib


def _sign(body: str) -> tuple[str, str]:
    """Build the (url, signature) pair exactly as Twilio does for a JSON webhook."""
    from hashlib import sha256

    from twilio.request_validator import RequestValidator

    body_hash = sha256(body.encode()).hexdigest()
    url = f"http://testserver/twilio/conversation-events?bodySHA256={body_hash}"
    # With bodySHA256 present, the signature covers the URL with empty params —
    # the body is verified via the hash, not folded into the signature.
    sig = RequestValidator(_TOKEN).compute_signature(url, "")
    return url, sig


def test_valid_bodysha256_signature_accepted(signed_client):
    import json

    body = json.dumps(_event("CONVERSATION_CREATED", {"id": "CO_sig", "status": "ACTIVE"}))
    url, sig = _sign(body)
    r = signed_client.post(
        url,
        content=body,
        headers={"X-Twilio-Signature": sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert "CO_sig" in [c["id"] for c in signed_client.get("/conversations").json()["conversations"]]


def test_missing_signature_rejected(signed_client):
    r = signed_client.post("/twilio/conversation-events", json=_event("CONVERSATION_CREATED", {"id": "x"}))
    assert r.status_code == 401


def test_bad_signature_rejected(signed_client):
    r = signed_client.post(
        "/twilio/conversation-events",
        json=_event("CONVERSATION_CREATED", {"id": "x"}),
        headers={"X-Twilio-Signature": "nope"},
    )
    assert r.status_code == 401
