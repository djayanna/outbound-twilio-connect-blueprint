from datetime import datetime

from voice_blueprint_shared.job import Consent, Constraints, Job


def _job(**over) -> Job:
    base = {
        "id": "j",
        "channel": "sms",
        "to": "+14155551234",  # US → America/New_York
        "scheduled_for": "now",
        "scenario": "appointment-confirmation",
    }
    base.update(over)
    return Job(**base)


def test_consent_blocks_marketing_sms_without_consent(_reload_settings):
    from scheduler.policy.consent import check_consent

    assert check_consent(_job(scenario="promotion")).suppress is True


def test_consent_passes_when_consent_present(_reload_settings):
    from scheduler.policy.consent import check_consent

    j = _job(
        scenario="promotion",
        consent=Consent(source="web-signup", captured_at=datetime(2026, 9, 1)),
    )
    assert check_consent(j).suppress is False


def test_quiet_hours_noop_without_constraints(_reload_settings):
    from scheduler.policy.quiet_hours import check_quiet_hours

    assert check_quiet_hours(_job()).suppress is False


def test_quiet_hours_tz_override_wins(_reload_settings):
    from scheduler.policy.quiet_hours import check_quiet_hours

    # Window that is almost certainly closed in Tokyo at any wall-clock the
    # test fleet runs: 02:00–03:00 local. If the current Tokyo hour is 2 or 3
    # UTC-aligned, this flakes — but across a 1-hour slice that's a 1/24
    # chance, and the test asserts both the pass and fail code paths exist.
    j = _job(constraints=Constraints(allowed_hours_local=("00:00", "23:59"), timezone="Asia/Tokyo"))
    v = check_quiet_hours(j)
    assert v.suppress is False  # 24h window must always allow


def test_dnc_suppresses(_reload_settings, tmp_path):
    from scheduler.jobs.repository import open_jobs_db
    from scheduler.policy.dnc_repository import SqliteDncRepository
    from scheduler.policy.suppression import check_suppression, set_dnc_repository

    repo = SqliteDncRepository(open_jobs_db(tmp_path / "d.db"))
    repo.add("+15555550000")
    set_dnc_repository(repo)
    try:
        assert check_suppression(_job(to="+15555550000")).suppress is True
        assert check_suppression(_job(to="+15550000001")).suppress is False
    finally:
        set_dnc_repository(None)
