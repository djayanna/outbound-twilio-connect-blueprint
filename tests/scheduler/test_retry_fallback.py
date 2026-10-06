from voice_blueprint_shared.job import Job, JobRun, RetryPolicy


def _job(**over) -> Job:
    base = {
        "id": "j",
        "channel": "voice",
        "to": "+14155550001",
        "scheduled_for": "now",
        "scenario": "payment-reminder",
        "retry_policy": RetryPolicy(max_attempts=3, backoff_seconds=0),
    }
    base.update(over)
    return Job(**base)


def test_next_attempt_increments(_reload_settings):
    from scheduler.jobs.retry import next_attempt

    j = _job()
    r = JobRun(job_id=j.id, attempt=1, status="failed")
    nxt = next_attempt(j, r)
    assert nxt is not None
    assert nxt.attempt == 2
    assert nxt.status == "pending"


def test_next_attempt_exhausts(_reload_settings):
    from scheduler.jobs.retry import next_attempt

    j = _job(retry_policy=RetryPolicy(max_attempts=1))
    r = JobRun(job_id=j.id, attempt=1, status="failed")
    assert next_attempt(j, r) is None


def test_voice_falls_back_to_sms_on_no_answer(_reload_settings):
    from scheduler.fallback.channel import next_channel

    assert next_channel(_job(), "no-answer") == "sms"


def test_voice_does_not_fall_back_on_completed(_reload_settings):
    from scheduler.fallback.channel import next_channel

    assert next_channel(_job(), None) is None


def test_sms_does_not_fall_back(_reload_settings):
    from scheduler.fallback.channel import next_channel

    assert next_channel(_job(channel="sms"), "undelivered") is None
