"""Thin facade over JobRepository.

Kept as `JobStore` so existing callers (routes, lifecycle, future worker) don't
move. The methods mirror what the in-memory store used to offer.
"""
from voice_blueprint_shared.job import Job, JobRun

from scheduler.jobs.repository import JobRepository


class JobStore:
    def __init__(self, repo: JobRepository) -> None:
        self._repo = repo

    def put_job(self, job: Job) -> None:
        self._repo.upsert_job(job)

    def get_job(self, job_id: str) -> Job | None:
        return self._repo.get_job(job_id)

    def list_jobs(self, status: str | None = None) -> list[Job]:
        return self._repo.list_jobs(status=status)

    def put_run(self, run: JobRun) -> None:
        self._repo.put_run(run)

    def runs_for(self, job_id: str) -> list[JobRun]:
        return self._repo.runs_for(job_id)

    def run_by_twilio_sid(self, sid: str) -> JobRun | None:
        return self._repo.run_by_twilio_sid(sid)

    def stats(self) -> dict:
        return self._repo.stats()
