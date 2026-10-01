from voice_blueprint_shared.job import Job

# TODO: load from sqlite / external source
_DNC: set[str] = set()


def check_suppression(job: Job):
    from scheduler.policy import Verdict

    if job.to in _DNC:
        return Verdict(suppress=True, reason="do_not_contact")
    return Verdict(suppress=False)
