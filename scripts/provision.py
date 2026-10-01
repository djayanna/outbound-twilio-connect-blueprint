"""Provision Twilio resources this blueprint needs and write IDs to .env.

Resources created:
  - Memory Store (memory.twilio.com)
  - Orchestrator Configuration (conversations.twilio.com/v2)
  - Intelligence Configuration (intelligence.twilio.com/v3)
  - Event Streams webhook sink → EVENT_INGESTOR_PUBLIC_URL

Usage:
  uv run python scripts/provision.py

See docs/03-twilio-provisioning.md for prerequisites.
"""
from __future__ import annotations

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


def main() -> None:
    print("voice-blueprint · Twilio provisioning")
    mem = create_memory_store()
    create_orchestrator_config(mem)
    create_intelligence_config()
    create_event_streams_sink()
    print("done.")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as e:
        print(f"Twilio API error: {e.response.status_code} {e.response.text}", file=sys.stderr)
        raise
