from pydantic import BaseModel
from voice_blueprint_shared.job import Job

from scheduler.jobs.store import JobStore
from scheduler.policy import check_all


class AcceptanceDecision(BaseModel):
    outcome: str  # "accepted" | "suppressed"
    reason: str | None = None


async def accept_job(job: Job, store: JobStore) -> AcceptanceDecision:
    verdict = check_all(job)
    if verdict.suppress:
        job.status = "cancelled"
        store.put_job(job)
        return AcceptanceDecision(outcome="suppressed", reason=verdict.reason)

    job.status = "scheduled" if job.scheduled_for != "now" else "firing"
    store.put_job(job)
    # TODO: enqueue for firing; call agent-connect at scheduled_for.
    return AcceptanceDecision(outcome="accepted", reason=None)
