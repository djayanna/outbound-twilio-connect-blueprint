from collections import defaultdict
from threading import Lock

from voice_blueprint_shared.job import Job, JobRun


class JobStore:
    """In-memory store. Swap for sqlite/postgres in prod."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._runs: dict[str, list[JobRun]] = defaultdict(list)
        self._lock = Lock()

    def put_job(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def get_job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self, status: str | None = None) -> list[Job]:
        if status is None:
            return list(self._jobs.values())
        return [j for j in self._jobs.values() if j.status == status]

    def put_run(self, run: JobRun) -> None:
        with self._lock:
            self._runs[run.job_id].append(run)

    def runs_for(self, job_id: str) -> list[JobRun]:
        return list(self._runs.get(job_id, []))

    def stats(self) -> dict:
        by_status: dict[str, int] = defaultdict(int)
        for j in self._jobs.values():
            by_status[j.status] += 1
        in_flight = sum(
            1 for runs in self._runs.values() for r in runs if r.status == "in-progress"
        )
        return {"jobs_by_status": dict(by_status), "runs_in_flight": in_flight}
