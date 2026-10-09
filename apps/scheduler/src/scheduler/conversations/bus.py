"""In-process pub/sub fan-out for live conversation deltas.

The Orchestrator webhook (`conversation_events.py`) publishes a small notify
delta after each upsert; the SSE endpoint (`conversations.py`) subscribes one
queue per connected wallboard and relays them. Deltas are intentionally tiny
— `{"type": ..., "conversation_id": ...}` — and the client refetches from the
local-DB read endpoints, so the stream format stays decoupled from Twilio's
resource shapes.

Single-process only: this is a plain in-memory bus. A multi-replica scheduler
would swap it for Redis pub/sub or similar; the subscribe/publish seam stays
the same.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any

# Bound each subscriber queue so one stalled connection can't grow unboundedly.
# On overflow we drop deltas — the client recovers on its next refetch, since
# deltas are notifications, not the source of truth.
_QUEUE_MAXSIZE = 100


class ConversationBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict[str, Any]) -> None:
        """Fan a delta out to every subscriber. Sync — safe to call from a handler."""
        for queue in list(self._subscribers):
            # Slow consumer; drop the delta — it catches up on its next refetch.
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


__all__ = ["ConversationBus"]
