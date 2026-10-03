"""Retry math.

Pure functions, no side effects — the caller (status callback handler) is
responsible for persisting the new JobRun. Backoff is linear via
`retry_policy.backoff_seconds` for now; swap in a bounded-exponential
scheme once there's a reason to.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from voice_blueprint_shared.job import Job, JobRun, RetryPolicy

_DEFAULT_POLICY = RetryPolicy()


def next_attempt(job: Job, last_run: JobRun) -> JobRun | None:
    """Return the next JobRun for this job, or None if attempts are exhausted."""
    policy = job.retry_policy or _DEFAULT_POLICY
    if last_run.attempt >= policy.max_attempts:
        return None
    delay = timedelta(seconds=policy.backoff_seconds * last_run.attempt)
    return JobRun(
        job_id=job.id,
        attempt=last_run.attempt + 1,
        status="pending",
        started_at=datetime.now(UTC) + delay,
    )


__all__ = ["next_attempt"]
