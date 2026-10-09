"""Live-delta fan-out: the in-process bus and the webhook→bus wiring.

The SSE endpoint itself is a thin StreamingResponse over the bus; we test the
bus contract (fan-out, bounded queue, unsubscribe) directly and assert that
posting an Orchestrator webhook publishes a delta a subscriber receives.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient
from scheduler.conversations.bus import ConversationBus


def test_bus_fans_out_to_all_subscribers():
    bus = ConversationBus()
    a = bus.subscribe()
    b = bus.subscribe()

    bus.publish({"type": "COMMUNICATION_CREATED", "conversation_id": "CO1"})

    assert a.get_nowait() == {"type": "COMMUNICATION_CREATED", "conversation_id": "CO1"}
    assert b.get_nowait() == {"type": "COMMUNICATION_CREATED", "conversation_id": "CO1"}


def test_bus_unsubscribe_stops_delivery():
    bus = ConversationBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.publish({"type": "x", "conversation_id": "CO1"})
    assert q.empty()
    assert bus.subscriber_count == 0


def test_bus_drops_on_full_queue_without_raising():
    """A stalled consumer must not break publish for everyone else."""
    bus = ConversationBus()
    q = bus.subscribe()
    # Fill well past the bound; publish must stay non-raising.
    for i in range(500):
        bus.publish({"type": "x", "conversation_id": f"CO{i}"})
    assert q.full()  # bounded, not unbounded


@pytest.fixture()
def client(_reload_settings):
    from scheduler.main import app
    with TestClient(app) as c:
        yield c


def test_webhook_publishes_delta_to_subscriber(client):
    bus = client.app.state.conversation_bus
    q = bus.subscribe()

    r = client.post("/twilio/conversation-events", json={
        "eventType": "COMMUNICATION_CREATED",
        "data": {
            "id": "CM1", "conversationId": "CO1",
            "author": {"address": "+18779213383", "channel": "VOICE"},
            "content": {"text": "Hi."},
            "occurredAt": "2026-10-09T07:06:09Z",
        },
    })
    assert r.status_code == 200
    assert q.get_nowait() == {"type": "COMMUNICATION_CREATED", "conversation_id": "CO1"}


def test_unhandled_event_publishes_nothing(client):
    bus = client.app.state.conversation_bus
    q = bus.subscribe()
    client.post("/twilio/conversation-events", json={"eventType": "NOPE", "data": {}})
    assert q.empty()


async def test_stream_endpoint_emits_connect_and_delta():
    """Drive the SSE generator directly: it primes, then relays a published delta."""
    from scheduler.http.conversations import stream

    bus = ConversationBus()

    class _Req:
        app = type("A", (), {"state": type("S", (), {"conversation_bus": bus})()})()

        async def is_disconnected(self):
            return False

    resp = await stream(_Req())
    agen = resp.body_iterator

    first = await agen.__anext__()
    assert first == ": connected\n\n"

    bus.publish({"type": "CONVERSATION_UPDATED", "conversation_id": "CO2"})
    second = await asyncio.wait_for(agen.__anext__(), timeout=2)
    assert second == 'data: {"type": "CONVERSATION_UPDATED", "conversation_id": "CO2"}\n\n'

    await agen.aclose()
