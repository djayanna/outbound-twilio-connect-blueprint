from datetime import UTC, datetime, timedelta

from voice_blueprint_shared.job import Job, JobRun


def _job(**over) -> Job:
    base = {
        "id": "job-1",
        "channel": "sms",
        "to": "+15555550001",
        "scheduled_for": "now",
        "scenario": "appointment-confirmation",
    }
    base.update(over)
    return Job(**base)


def test_upsert_and_get(_reload_settings, tmp_path):
    from scheduler.jobs.repository import SqliteJobRepository, open_jobs_db

    repo = SqliteJobRepository(open_jobs_db(tmp_path / "r.db"))
    j = _job()
    repo.upsert_job(j)
    assert repo.get_job("job-1").id == "job-1"


def test_list_runs_filter(_reload_settings, tmp_path):
    from scheduler.jobs.repository import SqliteJobRepository, open_jobs_db

    repo = SqliteJobRepository(open_jobs_db(tmp_path / "r.db"))
    repo.upsert_job(_job(id="a"))
    repo.upsert_job(_job(id="b"))
    repo.put_run(JobRun(job_id="a", attempt=1, status="completed"))
    repo.put_run(JobRun(job_id="b", attempt=1, status="failed"))
    assert {r.job_id for r in repo.list_runs(status="completed")} == {"a"}
    assert len(repo.list_runs(job_id="b")) == 1


def test_dedupe_claim_blocks_second(_reload_settings, tmp_path):
    from scheduler.jobs.repository import SqliteJobRepository, open_jobs_db

    repo = SqliteJobRepository(open_jobs_db(tmp_path / "r.db"))
    end = datetime.now(UTC) + timedelta(hours=1)
    assert repo.dedupe_claim("promo", "+15555550000", "a", end) is None
    assert repo.dedupe_claim("promo", "+15555550000", "b", end) == "a"
    # same job id re-claiming is idempotent
    assert repo.dedupe_claim("promo", "+15555550000", "a", end) is None


def test_dedupe_window_expiry(_reload_settings, tmp_path):
    from scheduler.jobs.repository import SqliteJobRepository, open_jobs_db

    repo = SqliteJobRepository(open_jobs_db(tmp_path / "r.db"))
    past = datetime.now(UTC) - timedelta(seconds=1)
    assert repo.dedupe_claim("promo", "+1555", "a", past) is None
    # window already expired; next attempt should succeed, not conflict
    future = datetime.now(UTC) + timedelta(hours=1)
    assert repo.dedupe_claim("promo", "+1555", "b", future) is None


def test_run_by_twilio_sid(_reload_settings, tmp_path):
    from scheduler.jobs.repository import SqliteJobRepository, open_jobs_db

    repo = SqliteJobRepository(open_jobs_db(tmp_path / "r.db"))
    repo.upsert_job(_job(id="a"))
    repo.put_run(JobRun(job_id="a", attempt=1, status="queued", twilio_call_sid="CA_1"))
    assert repo.run_by_twilio_sid("CA_1").job_id == "a"
    assert repo.run_by_twilio_sid("CA_missing") is None
