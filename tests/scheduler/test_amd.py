"""AMD (Answering Machine Detection) callback."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(_reload_settings):
    with patch(
        "scheduler.worker.loop.initiate_outbound",
        AsyncMock(return_value={"twilio_call_sid": "CA_amd"}),
    ):
        from scheduler.main import app
        with TestClient(app) as c:
            yield c


def _voice(**over):
    base = {
        "id": "j-amd",
        "channel": "voice",
        "to": "+14155550111",
        "scheduled_for": "now",
        "scenario": "payment-reminder",
        "context": {},
        "retry_policy": {"max_attempts": 2, "backoff_seconds": 0},
    }
    base.update(over)
    return base


def _wait_for_run(client, job_id, timeout=3):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        runs = client.get(f"/runs?job_id={job_id}").json()["runs"]
        if runs:
            return
        time.sleep(0.1)


def test_human_answer_is_noop(client):
    client.post("/jobs", json=_voice())
    _wait_for_run(client, "j-amd")
    client.post("/twilio/amd", data={"CallSid": "CA_amd", "AnsweredBy": "human"})
    run = client.get("/jobs/j-amd").json()["runs"][0]
    assert run["status"] == "queued"  # untouched
    assert run["terminal_reason"] is None


def test_unknown_answer_is_noop(client):
    """AMD timeout = treat as human (conservative)."""
    client.post("/jobs", json=_voice(id="j-amd-u"))
    _wait_for_run(client, "j-amd-u")
    client.post("/twilio/amd", data={"CallSid": "CA_amd", "AnsweredBy": "unknown"})
    run = client.get("/jobs/j-amd-u").json()["runs"][0]
    assert run["status"] == "queued"


def test_machine_answer_default_policy_is_hangup(client):
    """Default on_machine_answer=hangup → run fails voicemail, fallback to SMS."""
    client.post("/jobs", json=_voice(id="j-amd-m"))
    _wait_for_run(client, "j-amd-m")
    client.post("/twilio/amd", data={"CallSid": "CA_amd", "AnsweredBy": "machine_end_beep"})
    detail = client.get("/jobs/j-amd-m").json()
    assert detail["job"]["channel"] == "sms"  # fallback engaged
    runs = detail["runs"]
    assert runs[0]["status"] == "failed"
    assert runs[0]["terminal_reason"] == "voicemail"
    assert any(r["status"] == "pending" for r in runs)  # retry queued


def test_amd_missing_callsid_rejected(client):
    r = client.post("/twilio/amd", data={"AnsweredBy": "human"})
    assert r.status_code == 400


def test_amd_unmatched_sid_audited(client):
    r = client.post("/twilio/amd", data={"CallSid": "CA_nope", "AnsweredBy": "machine_end_beep"})
    assert r.status_code == 200  # still 200; audit records unmatched
    actions = [
        e["action"]
        for e in client.get("/audit?limit=50").json()["events"]
        if e["subject"] == "CA_nope"
    ]
    assert "run.unmatched" in actions


def test_machine_answer_leave_voicemail_policy(client):
    """on_machine_answer=leave_voicemail → no hangup; run tagged with answered_by."""
    client.post(
        "/jobs",
        json=_voice(id="j-amd-vm", context={"on_machine_answer": "leave_voicemail"}),
    )
    _wait_for_run(client, "j-amd-vm")
    client.post("/twilio/amd", data={"CallSid": "CA_amd", "AnsweredBy": "machine_end_beep"})
    detail = client.get("/jobs/j-amd-vm").json()
    assert detail["job"]["channel"] == "voice"  # no fallback
    run = detail["runs"][0]
    assert run["status"] == "queued"  # untouched
    assert run["terminal_reason"] is None
    assert run["answered_by"] == "machine_end_beep"


def test_runs_by_sid_lookup(client):
    """agent-connect polls this endpoint on each turn to pick up the AMD verdict."""
    client.post("/jobs", json=_voice(id="j-sid"))
    _wait_for_run(client, "j-sid")
    r = client.get("/runs/by-sid/CA_amd")
    assert r.status_code == 200
    body = r.json()
    assert body["run"]["job_id"] == "j-sid"
    assert body["job"]["id"] == "j-sid"
    # 404 on unknown
    assert client.get("/runs/by-sid/CA_nope").status_code == 404
