from typing import Literal

from pydantic import BaseModel
from voice_blueprint_shared.job import Job

from scheduler.jobs.store import JobStore
from scheduler.policy import check_all

# Every possible decision outcome `POST /jobs` can produce. Downstream
# consumers (upstream_callback POSTs, test-harness UI, the audit log)
# key off this exact set, so new values must be added here first.
DecisionOutcome = Literal["accepted", "suppressed", "duplicate"]


class AcceptanceDecision(BaseModel):
    """Decision returned by POST /jobs. Every branch of the submit flow
    returns one of these; downstream contracts validate against it.

    outcomes:
      - accepted:   job stored, worker will dispatch
      - suppressed: policy chain refused (DNC / consent / quiet hours /
                    dedupe) — see `reason` for which one
      - duplicate:  same `job.id` already submitted (idempotency); the
                    existing row is returned unchanged
    """

    outcome: DecisionOutcome
    reason: str | None = None


async def accept_job(job: Job, store: JobStore) -> AcceptanceDecision:
    verdict = check_all(job, store)
    if verdict.suppress:
        job.status = "cancelled"
        store.put_job(job)
        return AcceptanceDecision(outcome="suppressed", reason=verdict.reason)

    job.status = "scheduled" if job.scheduled_for != "now" else "firing"
    store.put_job(job)
    # The worker loop (scheduler/worker/loop.py) picks it up from here —
    # it promotes `scheduled` to `firing` when scheduled_for arrives and
    # calls agent-connect for `firing` jobs with no live run.
    return AcceptanceDecision(outcome="accepted", reason=None)
