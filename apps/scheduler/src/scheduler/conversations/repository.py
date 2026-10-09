"""Persistence for Conversation Orchestrator state.

Twilio's Conversation Orchestrator POSTs a webhook each time a conversation,
participant, or communication changes (see `scripts/provision.py` →
`statusCallbacks`). We mirror just enough of that state locally so the
wallboard can render a live transcript without polling Twilio's REST API.

Three tables, keyed by Twilio's own ids so webhook upserts are idempotent:

  * conversations  — one row per Conversation (status + last-activity clock)
  * participants   — the addresses/types in a Conversation (customer vs agent)
  * communications — the individual messages / voice-transcription fragments

Like `jobs/repository.py`, the authoritative copy of each resource is its
`payload` JSON column; the promoted columns are a query/index convenience.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id             TEXT PRIMARY KEY,
    status         TEXT,
    name           TEXT,
    created_at     TEXT,
    last_event_at  TEXT NOT NULL,
    payload        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_last_event ON conversations(last_event_at);

CREATE TABLE IF NOT EXISTS participants (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    type            TEXT,
    address         TEXT,
    channel         TEXT,
    payload         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_part_conv ON participants(conversation_id);

CREATE TABLE IF NOT EXISTS communications (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    channel         TEXT,
    author_address  TEXT,
    participant_id  TEXT,
    text            TEXT,
    occurred_at     TEXT,
    payload         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comm_conv ON communications(conversation_id);
CREATE INDEX IF NOT EXISTS idx_comm_occurred ON communications(conversation_id, occurred_at);
"""


def open_conversations_db(path: str | Path) -> sqlite3.Connection:
    """Open (and migrate) the conversations SQLite file. WAL for concurrent reads."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


class ConversationStore:
    """SQLite-backed mirror of Orchestrator conversations/participants/communications.

    All upserts are keyed on Twilio's ids and are safe to replay — the
    Orchestrator can resend a webhook, and voice captures arrive as many
    small fragments, so idempotency matters.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── writes (webhook ingest) ────────────────────────────────────────────
    def upsert_conversation(self, data: dict[str, Any]) -> str | None:
        conv_id = data.get("id") or data.get("conversationId")
        if not conv_id:
            return None
        self._conn.execute(
            """
            INSERT INTO conversations (id, status, name, created_at, last_event_at, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status        = excluded.status,
                name          = excluded.name,
                created_at    = COALESCE(excluded.created_at, conversations.created_at),
                last_event_at = excluded.last_event_at,
                payload       = excluded.payload
            """,
            (
                conv_id,
                data.get("status"),
                data.get("name"),
                data.get("createdAt"),
                _now_iso(),
                json.dumps(data),
            ),
        )
        return conv_id

    def upsert_participant(self, data: dict[str, Any]) -> str | None:
        part_id = data.get("id")
        conv_id = data.get("conversationId") or data.get("conversation_id")
        if not part_id or not conv_id:
            return None
        address, channel = _first_address(data.get("addresses"))
        self._conn.execute(
            """
            INSERT INTO participants (id, conversation_id, type, address, channel, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                conversation_id = excluded.conversation_id,
                type            = excluded.type,
                address         = excluded.address,
                channel         = excluded.channel,
                payload         = excluded.payload
            """,
            (part_id, conv_id, data.get("type"), address, channel, json.dumps(data)),
        )
        self._touch(conv_id)
        return conv_id

    def remove_participant(self, data: dict[str, Any]) -> str | None:
        part_id = data.get("id")
        if not part_id:
            return None
        row = self._conn.execute(
            "SELECT conversation_id FROM participants WHERE id = ?", (part_id,)
        ).fetchone()
        self._conn.execute("DELETE FROM participants WHERE id = ?", (part_id,))
        conv_id = row["conversation_id"] if row else None
        if conv_id:
            self._touch(conv_id)
        return conv_id

    def upsert_communication(self, data: dict[str, Any]) -> str | None:
        comm_id = data.get("id")
        conv_id = data.get("conversationId") or data.get("conversation_id")
        if not comm_id or not conv_id:
            return None
        author = data.get("author") or {}
        content = data.get("content") or {}
        self._conn.execute(
            """
            INSERT INTO communications
                (id, conversation_id, channel, author_address, participant_id,
                 text, occurred_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                channel        = excluded.channel,
                author_address = excluded.author_address,
                participant_id = excluded.participant_id,
                text           = excluded.text,
                occurred_at    = excluded.occurred_at,
                payload        = excluded.payload
            """,
            (
                comm_id,
                conv_id,
                author.get("channel"),
                author.get("address"),
                author.get("participantId"),
                content.get("text"),
                data.get("occurredAt") or data.get("createdAt"),
                json.dumps(data),
            ),
        )
        self._touch(conv_id)
        return conv_id

    def _touch(self, conv_id: str) -> None:
        """Bump a conversation's last-activity clock (orders the wallboard list).

        Participant/communication webhooks can arrive before the
        CONVERSATION_CREATED one, so insert a stub row if it's missing.
        """
        self._conn.execute(
            """
            INSERT INTO conversations (id, last_event_at, payload)
            VALUES (?, ?, '{}')
            ON CONFLICT(id) DO UPDATE SET last_event_at = excluded.last_event_at
            """,
            (conv_id, _now_iso()),
        )

    # ── reads (wallboard API) ──────────────────────────────────────────────
    def list_conversations(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, status, name, created_at, last_event_at
            FROM conversations
            ORDER BY last_event_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "status": r["status"],
                "name": r["name"],
                "created_at": r["created_at"],
                "last_event_at": r["last_event_at"],
                "participants": self._participants(r["id"]),
            }
            for r in rows
        ]

    def _participants(self, conv_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, type, address, channel FROM participants WHERE conversation_id = ?",
            (conv_id,),
        ).fetchall()
        return [
            {"id": r["id"], "type": r["type"], "address": r["address"], "channel": r["channel"]}
            for r in rows
        ]

    def communications(self, conv_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, channel, author_address, participant_id, text, occurred_at
            FROM communications
            WHERE conversation_id = ?
            ORDER BY occurred_at, id
            """,
            (conv_id,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "channel": r["channel"],
                "author_address": r["author_address"],
                "participant_id": r["participant_id"],
                "text": r["text"],
                "occurred_at": r["occurred_at"],
            }
            for r in rows
        ]


def _first_address(addresses: Any) -> tuple[str | None, str | None]:
    """Pull the first (address, channel) pair off a participant's addresses[]."""
    if isinstance(addresses, list) and addresses:
        first = addresses[0]
        if isinstance(first, dict):
            return first.get("address"), first.get("channel")
    return None, None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


__all__ = ["ConversationStore", "open_conversations_db"]
