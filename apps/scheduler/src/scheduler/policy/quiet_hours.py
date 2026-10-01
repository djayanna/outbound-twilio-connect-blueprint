from datetime import datetime

from voice_blueprint_shared.job import Job


def check_quiet_hours(job: Job):
    from scheduler.policy import Verdict

    c = job.constraints
    if not c or not c.allowed_hours_local:
        return Verdict(suppress=False)

    # TODO: real timezone lookup from phone number region. For now assume UTC.
    now = datetime.utcnow().time()
    start = datetime.strptime(c.allowed_hours_local[0], "%H:%M").time()
    end = datetime.strptime(c.allowed_hours_local[1], "%H:%M").time()

    if start <= now <= end:
        return Verdict(suppress=False)
    return Verdict(suppress=True, reason="outside_allowed_hours")
