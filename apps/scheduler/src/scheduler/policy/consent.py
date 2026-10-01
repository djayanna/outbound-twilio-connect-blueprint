from voice_blueprint_shared.job import Job


def check_consent(job: Job):
    from scheduler.policy import Verdict

    marketing_scenarios = {"promotion", "upsell"}
    if job.channel == "sms" and job.scenario in marketing_scenarios and not job.consent:
        return Verdict(suppress=True, reason="missing_consent")
    return Verdict(suppress=False)
