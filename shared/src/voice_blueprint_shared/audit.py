import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class AuditEvent(BaseModel):
    actor: str
    action: str
    subject: str
    data: dict[str, Any] = {}
    at: datetime | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       TEXT NOT NULL,
    actor    TEXT NOT NULL,
    action   TEXT NOT NULL,
    subject  TEXT NOT NULL,
    data     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit(at);
CREATE INDEX IF NOT EXISTS idx_audit_subject ON audit(subject);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit(action);

CREATE TABLE IF NOT EXISTS seen_events (
    event_id TEXT PRIMARY KEY,
    seen_at  TEXT NOT NULL
);
"""


def open_audit_db(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(_SCHEMA)
    return conn


def audit_record(conn: sqlite3.Connection, event: AuditEvent) -> None:
    at = (event.at or datetime.now(UTC)).isoformat()
    conn.execute(
        "INSERT INTO audit (at, actor, action, subject, data) VALUES (?, ?, ?, ?, ?)",
        (at, event.actor, event.action, event.subject, json.dumps(event.data)),
    )
