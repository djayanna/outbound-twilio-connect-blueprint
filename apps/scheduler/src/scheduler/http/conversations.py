"""Read API over the local Conversation mirror.

Serves the wallboard's Conversations view from the scheduler's own
`conversations.db` (populated by the Orchestrator webhook in
`conversation_events.py`) — no Twilio REST calls on the hot path. Commit 2
adds an SSE stream on top for live deltas; these endpoints handle the initial
hydrate and reconnect catch-up.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from scheduler.conversations.repository import ConversationStore

router = APIRouter()


def _conversations(req: Request) -> ConversationStore:
    return req.app.state.conversations


@router.get("/conversations")
def list_conversations(req: Request, limit: int = 100):
    """Most-recently-active conversations first, each with its participants."""
    return {"conversations": _conversations(req).list_conversations(limit=limit)}


@router.get("/conversations/{conversation_id}/communications")
def list_communications(conversation_id: str, req: Request):
    """The ordered transcript (messages + voice fragments) for one conversation."""
    return {"communications": _conversations(req).communications(conversation_id)}


__all__ = ["router"]
