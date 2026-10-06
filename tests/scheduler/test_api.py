"""End-to-end API tests via FastAPI TestClient. Twilio call stubbed."""
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


def _job(**over):
    base = {
        "id": "j1",
        "channel": "sms",
        "to": "+14155550001",
        "scheduled_for": "now",
        "scenario": "appointment-confirmation",
        "context": {},
    }
    base.update(over)
    return base


def test_post_jobs_accepted(client):
    r = client.post("/jobs", json=_job())
    assert r.status_code == 201
    assert r.json()["decision"]["outcome"] == "accepted"


def test_post_jobs_idempotent(client):
    client.post("/jobs", json=_job())
    r = client.post("/jobs", json=_job())
    decision = r.json()["decision"]
    assert decision["outcome"] == "duplicate"
    assert decision["reason"] == "job_id_already_submitted"


def test_duplicate_decision_validates(client):
    """The duplicate path must round-trip through AcceptanceDecision —
    an unknown outcome would raise, catching a drifted enum."""
    from scheduler.jobs.lifecycle import AcceptanceDecision

    client.post("/jobs", json=_job(id="dup-x"))
    r = client.post("/jobs", json=_job(id="dup-x"))
    # pydantic validates — this constructs cleanly only if outcome is
    # a Literal["accepted", "suppressed", "duplicate"].
    AcceptanceDecision.model_validate(r.json()["decision"])


def test_post_jobs_dedupes_different_id_same_scenario_to(client):
    client.post("/jobs", json=_job(id="a"))
    r = client.post("/jobs", json=_job(id="b"))
    assert r.json()["decision"]["outcome"] == "suppressed"
    assert "duplicate" in (r.json()["decision"]["reason"] or "")


def test_promotion_without_consent_suppressed(client):
    r = client.post("/jobs", json=_job(scenario="promotion"))
    assert r.json()["decision"]["outcome"] == "suppressed"


def test_dnc_add_blocks_submission(client):
    client.post("/dnc", json={"phone": "+14155550099", "reason": "opt-out"})
    r = client.post("/jobs", json=_job(id="x", to="+14155550099"))
    assert r.json()["decision"]["outcome"] == "suppressed"


def test_runs_endpoint(client):
    client.post("/jobs", json=_job())
    r = client.get("/runs")
    assert r.status_code == 200
    assert "runs" in r.json()
