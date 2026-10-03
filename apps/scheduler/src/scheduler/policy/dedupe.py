"""Dedupe policy: refuse a second (scenario, to) within the configured window.

The claim lives in SQLite and is cleared when it expires, so a repeat
outreach after the window re-acquires the slot cleanly. This is a
best-effort guard — the authoritative dedupe story is still "don't let
your upstream system submit the same intent twice."
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from voice_blueprint_shared.job import Job

from scheduler.config import settings
from scheduler.jobs.store import JobStore


def check_dedupe(job: Job, store: JobStore):
    from scheduler.policy import Verdict

    window = timedelta(seconds=settings.dedupe_window_seconds)
    holder = store.dedupe_claim(
        scenario=job.scenario,
        to_number=job.to,
        job_id=job.id,
        window_ends_at=datetime.now(UTC) + window,
    )
    if holder is None:
        return Verdict(suppress=False)
    return Verdict(suppress=True, reason=f"duplicate:held_by={holder}")
