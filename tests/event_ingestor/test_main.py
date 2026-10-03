"""event-ingestor validation + dedupe."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator


def _fresh_app():
    import sys

    for name in list(sys.modules):
        if name == "event_ingestor" or name.startswith("event_ingestor."):
            del sys.modules[name]
    import event_ingestor.main

    return event_ingestor.main.app


@pytest.fixture()
def dev_client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    with TestClient(_fresh_app()) as c:
        yield c


@pytest.fixture()
def signed_client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("DEV_MODE", "0")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret_token")
    with TestClient(_fresh_app()) as c:
        yield c


def test_dev_mode_accepts_unsigned(dev_client):
    r = dev_client.post("/twilio/events", json=[{"event_id": "e1", "type": "x"}])
    assert r.status_code == 200
    assert r.json() == {"processed": 1}


def test_dedupe_rejects_second(dev_client):
    dev_client.post("/twilio/events", json=[{"event_id": "e1", "type": "x"}])
    r = dev_client.post("/twilio/events", json=[{"event_id": "e1", "type": "x"}])
    assert r.json() == {"processed": 0}


def test_prod_rejects_missing_signature(signed_client):
    r = signed_client.post("/twilio/events", json=[{"event_id": "e1"}])
    assert r.status_code == 401


def test_prod_rejects_bad_signature(signed_client):
    r = signed_client.post(
        "/twilio/events",
        json=[{"event_id": "e1"}],
        headers={"X-Twilio-Signature": "nope"},
    )
    assert r.status_code == 401


def test_prod_accepts_valid_signature(signed_client):
    url = "http://testserver/twilio/events"
    sig = RequestValidator("secret_token").compute_signature(url, "")
    r = signed_client.post(
        "/twilio/events",
        json=[{"event_id": "e1"}],
        headers={"X-Twilio-Signature": sig},
    )
    assert r.status_code == 200
