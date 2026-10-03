"""Persistence for Jobs and JobRuns.

The repository defines the storage contract; SqliteJobRepository is the
in-process SQLite implementation shipped with the blueprint. Swap in a
Postgres implementation by writing a new class that satisfies the protocol
and wiring it in `main.py`.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from voice_blueprint_shared.job import Job, JobRun

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id             TEXT PRIMARY KEY,
    status         TEXT NOT NULL,
    scenario       TEXT NOT NULL,
    channel        TEXT NOT NULL,
    to_number      TEXT NOT NULL,
    scheduled_for  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    payload        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status    ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_scheduled ON jobs(scheduled_for);

CREATE TABLE IF NOT EXISTS job_runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id             TEXT NOT NULL REFERENCES jobs(id),
    attempt            INTEGER NOT NULL,
    status             TEXT NOT NULL,
    twilio_call_sid    TEXT,
    twilio_message_sid TEXT,
    conversation_id    TEXT,
    profile_id         TEXT,
    started_at         TEXT,
    ended_at           TEXT,
    terminal_reason    TEXT,
    created_at         TEXT NOT NULL,
    payload            TEXT NOT NULL,
    UNIQUE(job_id, attempt)
);
CREATE INDEX IF NOT EXISTS idx_runs_job     ON job_runs(job_id);
CREATE INDEX IF NOT EXISTS idx_runs_status  ON job_runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_call    ON job_runs(twilio_call_sid);
CREATE INDEX IF NOT EXISTS idx_runs_message ON job_runs(twilio_message_sid);
"""


def open_jobs_db(path: str | Path) -> sqlite3.Connection:
    """Open (and migrate) the jobs SQLite file. WAL mode for concurrent reads."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


class JobRepository(Protocol):
    """Storage contract. Swap SqliteJobRepository for a Postgres impl in prod."""

    def upsert_job(self, job: Job) -> None: ...
    def get_job(self, job_id: str) -> Job | None: ...
    def list_jobs(self, status: str | None = None) -> list[Job]: ...
    def put_run(self, run: JobRun) -> None: ...
    def runs_for(self, job_id: str) -> list[JobRun]: ...
    def run_by_twilio_sid(self, sid: str) -> JobRun | None: ...
    def list_runs(
        self, job_id: str | None = None, status: str | None = None, limit: int = 200
    ) -> list[JobRun]: ...
    def get_run(self, run_id: int) -> JobRun | None: ...
    def stats(self) -> dict: ...


class SqliteJobRepository:
    """SQLite-backed JobRepository. Connection is injected so callers manage lifecycle."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert_job(self, job: Job) -> None:
        now = _utc_now_iso()
        payload = job.model_dump_json(by_alias=True)
        scheduled = (
            job.scheduled_for
            if isinstance(job.scheduled_for, str)
            else job.scheduled_for.isoformat()
        )
        self._conn.execute(
            """
            INSERT INTO jobs (id, status, scenario, channel, to_number,
                              scheduled_for, created_at, updated_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status        = excluded.status,
                scheduled_for = excluded.scheduled_for,
                updated_at    = excluded.updated_at,
                payload       = excluded.payload
            """,
            (
                job.id, job.status, job.scenario, job.channel, job.to,
                scheduled, now, now, payload,
            ),
        )

    def get_job(self, job_id: str) -> Job | None:
        row = self._conn.execute(
            "SELECT payload FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return Job.model_validate_json(row["payload"]) if row else None

    def list_jobs(self, status: str | None = None) -> list[Job]:
        if status is None:
            rows = self._conn.execute("SELECT payload FROM jobs ORDER BY created_at DESC")
        else:
            rows = self._conn.execute(
                "SELECT payload FROM jobs WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        return [Job.model_validate_json(r["payload"]) for r in rows.fetchall()]

    def put_run(self, run: JobRun) -> None:
        payload = run.model_dump_json()
        self._conn.execute(
            """
            INSERT INTO job_runs (job_id, attempt, status, twilio_call_sid,
                                  twilio_message_sid, conversation_id, profile_id,
                                  started_at, ended_at, terminal_reason,
                                  created_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, attempt) DO UPDATE SET
                status             = excluded.status,
                twilio_call_sid    = excluded.twilio_call_sid,
                twilio_message_sid = excluded.twilio_message_sid,
                conversation_id    = excluded.conversation_id,
                profile_id         = excluded.profile_id,
                started_at         = excluded.started_at,
                ended_at           = excluded.ended_at,
                terminal_reason    = excluded.terminal_reason,
                payload            = excluded.payload
            """,
            (
                run.job_id, run.attempt, run.status,
                run.twilio_call_sid, run.twilio_message_sid,
                run.conversation_id, run.profile_id,
                run.started_at.isoformat() if run.started_at else None,
                run.ended_at.isoformat() if run.ended_at else None,
                run.terminal_reason,
                _utc_now_iso(), payload,
            ),
        )

    def runs_for(self, job_id: str) -> list[JobRun]:
        rows = self._conn.execute(
            "SELECT payload FROM job_runs WHERE job_id = ? ORDER BY attempt",
            (job_id,),
        ).fetchall()
        return [JobRun.model_validate_json(r["payload"]) for r in rows]

    def run_by_twilio_sid(self, sid: str) -> JobRun | None:
        """Find the JobRun matching a Twilio Call or Message SID. Used by status callbacks."""
        row = self._conn.execute(
            """
            SELECT payload FROM job_runs
            WHERE twilio_call_sid = ? OR twilio_message_sid = ?
            ORDER BY id DESC LIMIT 1
            """,
            (sid, sid),
        ).fetchone()
        return JobRun.model_validate_json(row["payload"]) if row else None

    def list_runs(
        self, job_id: str | None = None, status: str | None = None, limit: int = 200
    ) -> list[JobRun]:
        clauses: list[str] = []
        params: list = []
        if job_id is not None:
            clauses.append("job_id = ?")
            params.append(job_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT payload FROM job_runs {where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        return [JobRun.model_validate_json(r["payload"]) for r in rows]

    def get_run(self, run_id: int) -> JobRun | None:
        row = self._conn.execute(
            "SELECT payload FROM job_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return JobRun.model_validate_json(row["payload"]) if row else None

    def stats(self) -> dict:
        by_status: dict[str, int] = defaultdict(int)
        for row in self._conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"):
            by_status[row["status"]] = row["n"]
        in_flight = self._conn.execute(
            "SELECT COUNT(*) AS n FROM job_runs WHERE status = 'in-progress'"
        ).fetchone()["n"]
        return {"jobs_by_status": dict(by_status), "runs_in_flight": in_flight}


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


__all__ = ["JobRepository", "SqliteJobRepository", "open_jobs_db"]
