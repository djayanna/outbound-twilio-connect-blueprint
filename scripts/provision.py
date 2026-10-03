"""Provision Twilio resources this blueprint needs and write IDs to .env.

Resources managed:
  - Memory Store (memory.twilio.com)
  - Orchestrator Configuration (conversations.twilio.com/v2)
  - Intelligence Configuration (intelligence.twilio.com/v3)
  - Event Streams webhook sink → EVENT_INGESTOR_PUBLIC_URL
  - Event Streams Subscription linking the sink to the event types the
    event-ingestor filters on

Idempotent: if an SID is already present in .env and the resource still
exists on Twilio, the script reuses it. Only missing / stale resources
are created. Pass `--force` to recreate everything from scratch (useful
if you've changed names, Configuration shape, or want a clean slate).

Usage:
  uv run python scripts/provision.py
  uv run python scripts/provision.py --force

See docs/02-twilio-provisioning.md for prerequisites.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import cast

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
# step logs the error and bails without wedging the earlier steps.
# Twilio-authored (prebuilt) operators we attach to the Intelligence Config.
# Catalog: https://www.twilio.com/docs/conversations/intelligence/use-twilio-authored-language-operators
#
# To add a *custom* operator (e.g. a consent-capture operator you define in
# the Twilio console), paste its SID below alongside the prebuilt ones; the
# shape is the same.
INTELLIGENCE_OPERATORS: list[str] = [
    # Summary — post-call human-readable summary. 3–5 sentences by default.
    "intelligence_operator_01kcv35pnkeysaf6z6cqtbpegn",
    # Sentiment — positive / negative / neutral / mixed on the full conversation.
    "intelligence_operator_01kcrvw16kfa88qvgrfmr7y151",
]


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


def _exists(url: str) -> bool:
    """Return True iff a GET on `url` succeeds (200). Used to decide whether
    an SID we have in .env is still a live resource on Twilio."""
    try:
        r = httpx.get(url, auth=AUTH, timeout=10)
    except httpx.HTTPError:
        return False
    return r.status_code == 200


def ensure_memory_store(force: bool) -> str:
    sid = os.getenv("TWILIO_MEMORY_STORE_ID", "")
    if sid and not force and _exists(f"https://memory.twilio.com/v1/Services/{sid}"):
        print(f"reusing Memory Store {sid}")
        return sid

    print("creating Memory Store…")
    r = httpx.post(
        "https://memory.twilio.com/v1/Services",
        auth=AUTH,
        json={"uniqueName": "voice-blueprint", "friendlyName": "voice-blueprint memory"},
        timeout=30,
    )
    if r.status_code == 404:
        # Twilio returns 20404 "resource not found" on POST /v1/Services when
        # the Conversation Memory product isn't enabled on the account. The
        # rest of the blueprint (scheduler, retry/fallback, AMD, Intelligence)
        # works fine without Memory; log a clear pointer and continue.
        print(
            "  SKIP: Conversation Memory not enabled on this account.\n"
            "  Enable it in the Twilio Console (Products → Conversation Memory)\n"
            "  or contact your Twilio account team, then re-run provision.py.\n"
            "  Downstream steps (Orchestrator, Intelligence, Event Streams)\n"
            "  will proceed without a memory_store_id.",
            file=sys.stderr,
        )
        return ""
    r.raise_for_status()
    sid = r.json()["sid"]
    _write_env("TWILIO_MEMORY_STORE_ID", sid)
    return sid


def ensure_orchestrator_config(memory_store_id: str, force: bool) -> str:
    sid = os.getenv("TWILIO_CONVERSATION_CONFIGURATION_ID", "")
    if (
        sid
        and not force
        and _exists(f"https://conversations.twilio.com/v2/ControlPlane/Configurations/{sid}")
    ):
        print(f"reusing Orchestrator Configuration {sid}")
        return sid

    print("creating Orchestrator Configuration…")
    if not PHONE:
        print("  WARN: TWILIO_PHONE_NUMBER not set; capture rules will be left empty")

    body: dict = {
        "displayName": "voice-blueprint-config",
        "conversationGroupingType": "GROUP_BY_PROFILE",
        "channelSettings": {},
    }
    # Only attach Memory when the account has it enabled — otherwise
    # Orchestrator rejects memoryStoreId with its own 404.
    if memory_store_id:
        body["memoryStoreId"] = memory_store_id
        body["memoryExtractionEnabled"] = True
    else:
        print("  (no memory_store_id — creating configuration without Memory)")

    body["channelSettings"] = {
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
    }

    r = httpx.post(
        "https://conversations.twilio.com/v2/ControlPlane/Configurations",
        auth=AUTH,
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    resp = r.json()
    config_id = resp.get("id") or resp.get("operation", {}).get("resource", {}).get("id", "")
    _write_env("TWILIO_CONVERSATION_CONFIGURATION_ID", config_id)
    return config_id


def ensure_intelligence_config(force: bool) -> str:
    sid = os.getenv("TWILIO_INTELLIGENCE_CONFIGURATION_ID", "")
    if (
        sid
        and not force
        and _exists(f"https://intelligence.twilio.com/v3/ControlPlane/Configurations/{sid}")
    ):
        print(f"reusing Intelligence Configuration {sid}")
        return sid

    print("creating Intelligence Configuration…")
    r = httpx.post(
        "https://intelligence.twilio.com/v3/ControlPlane/Configurations",
        auth=AUTH,
        json={
            "displayName": "voice-blueprint-intelligence",
            # All operators fire at CONVERSATION_END — i.e. post-call. Switch
            # specific rules to TRANSCRIPT_SEGMENT if you want real-time
            # agent-assist / live compliance signals.
            "rules": [
                {
                    "operators": [{"id": op} for op in INTELLIGENCE_OPERATORS],
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


def ensure_event_streams_sink(force: bool) -> str:
    if not EVENT_INGESTOR_PUBLIC_URL:
        print("skipping Event Streams sink — set EVENT_INGESTOR_PUBLIC_URL to enable")
        return ""

    sid = os.getenv("TWILIO_EVENT_STREAMS_SINK_SID", "")
    if sid and not force and _exists(f"https://events.twilio.com/v1/Sinks/{sid}"):
        print(f"reusing Event Streams sink {sid}")
        return sid

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


def ensure_event_streams_subscription(sink_sid: str, force: bool) -> str:
    """Link the sink to the event types we care about.

    A sink with no subscriptions receives nothing — this step is what
    actually makes events flow. Twilio accepts `Types` as a repeated form
    field; each is a JSON object with `type` and `schema_version`.
    """
    if not sink_sid:
        print("skipping Event Streams subscription — no sink to attach")
        return ""

    sid = os.getenv("TWILIO_EVENT_STREAMS_SUBSCRIPTION_SID", "")
    if sid and not force and _exists(f"https://events.twilio.com/v1/Subscriptions/{sid}"):
        print(f"reusing Event Streams subscription {sid}")
        return sid

    print("creating Event Streams subscription…")
    # Repeated `Types` form field — one entry per subscribed event type.
    # httpx accepts list[tuple[str, str]] at runtime for this; typeshed is
    # narrower, hence the cast.
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
    parser = argparse.ArgumentParser(description="Provision Twilio resources for the blueprint.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recreate every resource even if an SID is already set in .env.",
    )
    args = parser.parse_args()

    print("voice-blueprint · Twilio provisioning" + (" (--force)" if args.force else ""))
    mem = ensure_memory_store(args.force)
    ensure_orchestrator_config(mem, args.force)
    ensure_intelligence_config(args.force)
    sink = ensure_event_streams_sink(args.force)
    ensure_event_streams_subscription(sink, args.force)
    print("done.")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as e:
        print(f"Twilio API error: {e.response.status_code} {e.response.text}", file=sys.stderr)
        raise
