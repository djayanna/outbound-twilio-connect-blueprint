from dataclasses import dataclass

from voice_blueprint_shared.job import Job

from scheduler.policy.consent import check_consent
from scheduler.policy.quiet_hours import check_quiet_hours
from scheduler.policy.suppression import check_suppression


@dataclass
class Verdict:
    suppress: bool
    reason: str | None = None


def check_all(job: Job) -> Verdict:
    for check in (check_suppression, check_consent, check_quiet_hours):
        v = check(job)
        if v.suppress:
            return v
    return Verdict(suppress=False)
