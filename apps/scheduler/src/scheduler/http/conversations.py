"""Read API over the local Conversation mirror.

Serves the wallboard's Conversations view from the scheduler's own
`conversations.db` (populated by the Orchestrator webhook in
`conversation_events.py`) — no Twilio REST calls on the hot path. Commit 2
adds an SSE stream on top for live deltas; these endpoints handle the initial
hydrate and reconnect catch-up.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from scheduler.conversations.bus import ConversationBus
from scheduler.conversations.repository import ConversationStore

router = APIRouter()

# How often to emit an SSE keepalive comment when no deltas are flowing. Keeps
# proxies/load balancers from reaping an idle connection.
_KEEPALIVE_SECONDS = 15


def _conversations(req: Request) -> ConversationStore:
    return req.app.state.conversations


def _bus(req: Request) -> ConversationBus:
    return req.app.state.conversation_bus


@router.get("/conversations")
def list_conversations(req: Request, limit: int = 100):
    """Most-recently-active conversations first, each with its participants."""
    return {"conversations": _conversations(req).list_conversations(limit=limit)}


@router.get("/conversations/{conversation_id}/communications")
def list_communications(conversation_id: str, req: Request):
    """The ordered transcript (messages + voice fragments) for one conversation."""
    return {"communications": _conversations(req).communications(conversation_id)}


@router.get("/conversations/stream")
async def stream(req: Request) -> StreamingResponse:
    """Server-Sent Events of live conversation deltas.

    Each `data:` line is a JSON notify hint — `{type, conversation_id}` — that
    tells the wallboard which conversation changed; the client then refetches
    the list / transcript from the read endpoints above. A periodic `:` comment
    keeps the connection warm through idle gaps.
    """
    bus = _bus(req)
    queue = bus.subscribe()

    async def gen():
        try:
            # Prime the stream so the client's EventSource `onopen` fires
            # promptly even before any traffic.
            yield ": connected\n\n"
            while True:
                if await req.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # defeat proxy buffering (nginx)
        },
    )


__all__ = ["router"]
