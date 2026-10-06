"""Do-Not-Contact storage.

Protocol + SQLite impl. The repository owns the schema and keeps the DNC
list in the same database as Jobs so ops endpoints and policy checks see
one source of truth. Swap in a Redis/CDN-backed implementation in prod
with the same interface.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Protocol

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dnc (
    phone       TEXT PRIMARY KEY,
    reason      TEXT,
    added_at    TEXT NOT NULL
);
"""


class DncRepository(Protocol):
    def contains(self, phone: str) -> bool: ...
    def add(self, phone: str, reason: str | None = None) -> None: ...
    def remove(self, phone: str) -> bool: ...
    def list(self) -> list[dict]: ...


class SqliteDncRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(_SCHEMA)

    def contains(self, phone: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM dnc WHERE phone = ?", (phone,)
        ).fetchone()
        return row is not None

    def add(self, phone: str, reason: str | None = None) -> None:
        self._conn.execute(
            """
            INSERT INTO dnc (phone, reason, added_at) VALUES (?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET reason = excluded.reason
            """,
            (phone, reason, datetime.now(UTC).isoformat()),
        )

    def remove(self, phone: str) -> bool:
        cur = self._conn.execute("DELETE FROM dnc WHERE phone = ?", (phone,))
        return (cur.rowcount or 0) > 0

    def list(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT phone, reason, added_at FROM dnc ORDER BY added_at DESC"
        ).fetchall()
        return [
            {"phone": r["phone"], "reason": r["reason"], "added_at": r["added_at"]}
            for r in rows
        ]


__all__ = ["DncRepository", "SqliteDncRepository"]
