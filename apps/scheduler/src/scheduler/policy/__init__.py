from dataclasses import dataclass

from voice_blueprint_shared.job import Job

from scheduler.jobs.store import JobStore
from scheduler.policy.consent import check_consent
from scheduler.policy.dedupe import check_dedupe
from scheduler.policy.quiet_hours import check_quiet_hours
from scheduler.policy.suppression import check_suppression


@dataclass
class Verdict:
    suppress: bool
    reason: str | None = None


def check_all(job: Job, store: JobStore) -> Verdict:
    # Order matters:
    #   * DNC first — if the number is blocked, don't claim a dedupe slot.
    #   * Consent — refuses marketing SMS without a documented source.
    #   * Quiet hours — timezone-aware; last cheap check.
    #   * Dedupe — writes to SQLite; comes after all read-only guards so a
    #     later-rejected job doesn't poison the (scenario, to) window.
    for check in (check_suppression, check_consent, check_quiet_hours):
        v = check(job)
        if v.suppress:
            return v
    return check_dedupe(job, store)
