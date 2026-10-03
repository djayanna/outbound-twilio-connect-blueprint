"""Provision Twilio resources this blueprint needs and write IDs to .env.

Resources created:
  - Memory Store (memory.twilio.com)
  - Orchestrator Configuration (conversations.twilio.com/v2)
  - Intelligence Configuration (intelligence.twilio.com/v3)
  - Event Streams webhook sink → EVENT_INGESTOR_PUBLIC_URL
  - Event Streams Subscription linking the sink to the event types the
    event-ingestor filters on

Usage:
  uv run python scripts/provision.py

See docs/02-twilio-provisioning.md for prerequisites.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
PHONE = os.environ.get("TWILIO_PHONE_NUMBER", "")
EVENT_INGESTOR_PUBLIC_URL = os.environ.get("EVENT_INGESTOR_PUBLIC_URL", "")

AUTH = (ACCOUNT_SID, AUTH_TOKEN)
ENV_PATH = Path(".env")


# Event types the ingestor's routing table filters on. Each entry is
# {type, schema_version}; schema versions move slowly and are listed at
# https://events.twilio.com/v1/Types and in the Twilio console.
# If a type is rejected (unknown name / wrong version), the subscribe
# step logs the error and continues with the rest — tweak this list
# instead of hunting the error down.
SUBSCRIPTION_TYPES: list[dict] = [
    # Voice call lifecycle — redundant with the per-call statusCallback the
    # scheduler already receives, but useful as a backchannel + for calls
    # that bypass our outbound (e.g. inbound).
    {"type": "com.twilio.voice.status-callback.call.initiated", "schema_version": 1},
    {"type": "com.twilio.voice.status-callback.call.ringing", "schema_version": 1},
    {"type": "com.twilio.voice.status-callback.call.answered", "schema_version": 1},
    {"type": "com.twilio.voice.status-callback.call.completed", "schema_version": 1},
    # Messaging delivery status — same story as voice.
    {"type": "com.twilio.messaging.message.sent", "schema_version": 1},
    {"type": "com.twilio.messaging.message.delivered", "schema_version": 1},
    {"type": "com.twilio.messaging.message.undelivered", "schema_version": 1},
    {"type": "com.twilio.messaging.message.failed", "schema_version": 1},
    # Intelligence operator result — ONLY arrives via Event Streams; this
    # is why the subscription matters even if you ignore voice/SMS above.
    {"type": "com.twilio.intelligence.operator-result.created", "schema_version": 1},
]


def _write_env(key: str, value: str) -> None:
    text = ENV_PATH.read_text() if ENV_PATH.exists() else ""
    lines = text.splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n")
    print(f"  wrote {key}={value}")


def create_memory_store() -> str:
    print("creating Memory Store…")
    r = httpx.post(
        "https://memory.twilio.com/v1/Services",
        auth=AUTH,
        json={"uniqueName": "voice-blueprint", "friendlyName": "voice-blueprint memory"},
        timeout=30,
    )
    r.raise_for_status()
    sid = r.json()["sid"]
    _write_env("TWILIO_MEMORY_STORE_ID", sid)
    return sid


def create_orchestrator_config(memory_store_id: str) -> str:
    print("creating Orchestrator Configuration…")
    if not PHONE:
        print("  WARN: TWILIO_PHONE_NUMBER not set; capture rules will be left empty")
    r = httpx.post(
        "https://conversations.twilio.com/v2/ControlPlane/Configurations",
        auth=AUTH,
        json={
            "displayName": "voice-blueprint-config",
            "conversationGroupingType": "GROUP_BY_PROFILE",
            "memoryStoreId": memory_store_id,
            "memoryExtractionEnabled": True,
            "channelSettings": {
                "SMS": {
                    "captureRules": (
                        [
                            {"from": PHONE, "to": "*", "metadata": {}},
                            {"from": "*", "to": PHONE, "metadata": {}},
                        ]
                        if PHONE
                        else []
                    ),
                    "statusTimeouts": {"inactive": 10, "closed": 60},
                },
                # VOICE: active TwiML, no capture rules — avoid double STT billing.
                "VOICE": {"statusTimeouts": {"inactive": 10, "closed": 60}},
            },
        },
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    config_id = body.get("id") or body.get("operation", {}).get("resource", {}).get("id", "")
    _write_env("TWILIO_CONVERSATION_CONFIGURATION_ID", config_id)
    return config_id


def create_intelligence_config() -> str:
    print("creating Intelligence Configuration…")
    r = httpx.post(
        "https://intelligence.twilio.com/v3/ControlPlane/Configurations",
        auth=AUTH,
        json={
            "displayName": "voice-blueprint-intelligence",
            "rules": [
                {
                    "operators": [
                        # Twilio-authored Summary — fires at CONVERSATION_END
                        {"id": "intelligence_operator_01kcv35pnkeysaf6z6cqtbpegn"}
                    ],
                    "triggers": [{"on": "CONVERSATION_END"}],
                    "actions": [],
                }
            ],
        },
        timeout=30,
    )
    r.raise_for_status()
    config_id = r.json().get("id", "")
    _write_env("TWILIO_INTELLIGENCE_CONFIGURATION_ID", config_id)
    return config_id


def create_event_streams_sink() -> str:
    if not EVENT_INGESTOR_PUBLIC_URL:
        print("skipping Event Streams sink — set EVENT_INGESTOR_PUBLIC_URL to enable")
        return ""
    print("creating Event Streams webhook sink…")
    r = httpx.post(
        "https://events.twilio.com/v1/Sinks",
        auth=AUTH,
        data={
            "Description": "voice-blueprint event-ingestor",
            "SinkType": "webhook",
            "SinkConfiguration": (
                '{"destination":"' + EVENT_INGESTOR_PUBLIC_URL
                + '/twilio/events","method":"POST","batch_events":true}'
            ),
        },
        timeout=30,
    )
    r.raise_for_status()
    sid = r.json()["sid"]
    _write_env("TWILIO_EVENT_STREAMS_SINK_SID", sid)
    return sid


def create_event_streams_subscription(sink_sid: str) -> str:
    """Link the sink to the event types we care about.

    A sink with no subscriptions receives nothing — this step is what
    actually makes events flow. Twilio accepts `Types` as a repeated form
    field; each is a JSON object with `type` and `schema_version`.
    """
    if not sink_sid:
        print("skipping Event Streams subscription — no sink to attach")
        return ""
    print("creating Event Streams subscription…")
    # Repeated `Types` form field — one entry per subscribed event type.
    # httpx accepts list[tuple[str, str]] at runtime for this; typeshed is
    # narrower, hence the cast.
    from typing import cast

    data: list[tuple[str, str]] = [
        ("Description", "voice-blueprint"),
        ("SinkSid", sink_sid),
        *(("Types", json.dumps(t)) for t in SUBSCRIPTION_TYPES),
    ]
    r = httpx.post(
        "https://events.twilio.com/v1/Subscriptions",
        auth=AUTH,
        data=cast("dict", data),
        timeout=30,
    )
    if r.status_code >= 400:
        # Partial failure — print the body and bail cleanly so operators can
        # fix the Types list without re-running the whole script.
        print(
            f"  subscription create failed: {r.status_code} {r.text}\n"
            "  (unknown type names or wrong schema_version are the usual cause;\n"
            "  inspect https://events.twilio.com/v1/Types to reconcile and "
            "edit SUBSCRIPTION_TYPES in scripts/provision.py)",
            file=sys.stderr,
        )
        return ""
    sid = r.json()["sid"]
    _write_env("TWILIO_EVENT_STREAMS_SUBSCRIPTION_SID", sid)
    return sid


def main() -> None:
    print("voice-blueprint · Twilio provisioning")
    mem = create_memory_store()
    create_orchestrator_config(mem)
    create_intelligence_config()
    sink = create_event_streams_sink()
    create_event_streams_subscription(sink)
    print("done.")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as e:
        print(f"Twilio API error: {e.response.status_code} {e.response.text}", file=sys.stderr)
        raise
