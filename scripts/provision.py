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
    # Names are verified against GET https://events.twilio.com/v1/Types on a
    # live account. If a subscription create ever returns 20409 "Type … not
    # found in the system", that endpoint is the canonical list — browse it
    # in the Twilio console or `twilio api:events:v1:types:list`.
    #
    # We intentionally omit `schema_version` so Twilio uses the latest. New
    # schemas usually add nullable fields; the ingestor's loose routing
    # tolerates that.

    # Voice call lifecycle — redundant with the per-call statusCallback the
    # scheduler already receives, but useful as a backchannel + for calls
    # that bypass our outbound (e.g. inbound).
    {"type": "com.twilio.voice.status-callback.call.initiated"},
    {"type": "com.twilio.voice.status-callback.call.ringing"},
    {"type": "com.twilio.voice.status-callback.call.answered"},
    {"type": "com.twilio.voice.status-callback.call.completed"},
    # AMD verdict — fires when async machine-detection resolves.
    {"type": "com.twilio.voice.status-callback.amd.detected"},

    # Messaging delivery status.
    {"type": "com.twilio.messaging.message.sent"},
    {"type": "com.twilio.messaging.message.delivered"},
    {"type": "com.twilio.messaging.message.undelivered"},
    {"type": "com.twilio.messaging.message.failed"},

    # NOTE: Conversation Intelligence event types
    # (com.twilio.engagement-intelligence.transcript.*) are restricted/
    # beta — Twilio returns 20409 "is restricted" on subscribe for most
    # accounts. If your account has access, add them here:
    #
    #   {"type": "com.twilio.engagement-intelligence.transcript.operators.results-available"},
    #   {"type": "com.twilio.engagement-intelligence.transcript.finished"},
    #
    # Operator results are also available via the Intelligence v3 API
    # (poll the configuration's /Results endpoint) as a fallback.
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


_MEMORY_STORE_BASE = "https://memory.twilio.com/v1/ControlPlane/Stores"


def ensure_memory_store(force: bool) -> str:
    sid = os.getenv("TWILIO_MEMORY_STORE_ID", "")
    if sid and not force and _exists(f"{_MEMORY_STORE_BASE}/{sid}"):
        print(f"reusing Memory Store {sid}")
        return sid

    print("creating Memory Store…")
    r = httpx.post(
        _MEMORY_STORE_BASE,
        auth=AUTH,
        # displayName must match ^[a-zA-Z0-9-]+$ — no underscores, no dots.
        json={
            "displayName": "voice-blueprint",
            "description": "voice-blueprint memory store",
        },
        timeout=30,
    )
    if r.status_code == 404:
        print(
            "  SKIP: Conversation Memory not reachable on this account.\n"
            "  If this persists after enabling the product in the Twilio\n"
            "  Console, contact your Twilio account team.\n"
            "  The Orchestrator step will skip downstream.",
            file=sys.stderr,
        )
        return ""
    r.raise_for_status()
    body = r.json()
    status_url = body.get("statusUrl")
    if not status_url:
        print(f"  WARN: create response missing statusUrl: {body}", file=sys.stderr)
        return ""

    # Memory Store creation is async — poll statusUrl until ACTIVE.
    sid = _wait_for_memory_store(status_url)
    if sid:
        _write_env("TWILIO_MEMORY_STORE_ID", sid)
    return sid


def _wait_for_memory_store(status_url: str, timeout_s: int = 120) -> str:
    """Poll until the Memory Store reaches ACTIVE. Returns the store id or ""."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = httpx.get(status_url, auth=AUTH, timeout=15)
        if r.status_code != 200:
            print(f"  statusUrl probe {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return ""
        body = r.json()
        status = body.get("status")
        sid = body.get("id") or body.get("storeId") or body.get("resource", {}).get("id", "")
        if status == "ACTIVE" and sid:
            print(f"  Memory Store ACTIVE: {sid}")
            return sid
        if status == "FAILED":
            print(f"  Memory Store provisioning FAILED: {body}", file=sys.stderr)
            return ""
        print(f"  Memory Store status={status}; waiting…")
        time.sleep(3)
    print("  Memory Store did not reach ACTIVE within the timeout", file=sys.stderr)
    return ""


def _orchestrator_body(memory_store_id: str, intelligence_config_id: str) -> dict:
    """Build the Orchestrator Configuration request body.

    Capture rules are what tell Twilio Orchestrator to persist a Call /
    Message into a Conversation (which is what Memory and Intelligence
    then process). Without rules, Memory never ingests the transcript
    and no observations are written. We opt both VOICE and SMS in for
    traffic to/from our Twilio number.

    statusCallbacks points at agent-connect's /webhook — TAC's SMSChannel
    + conversation webhook handler lives there. Without this, inbound SMS
    replies never reach the LLM.
    """
    rules = (
        [
            {"from": PHONE, "to": "*", "metadata": {}},
            {"from": "*", "to": PHONE, "metadata": {}},
        ]
        if PHONE
        else []
    )
    body: dict = {
        "displayName": "voice-blueprint-config",
        "description": "voice-blueprint orchestrator configuration",
        "conversationGroupingType": "GROUP_BY_PROFILE",
        "memoryStoreId": memory_store_id,
        "memoryExtractionEnabled": True,
        "channelSettings": {
            "SMS": {
                "captureRules": rules,
                "statusTimeouts": {"inactive": 10, "closed": 60},
            },
            # VOICE capture is REQUIRED for Memory extraction. Twilio runs
            # STT once as part of ConversationRelay; the "double STT"
            # concern earlier was wrong — capture piggybacks on the
            # existing transcript.
            "VOICE": {
                "captureRules": rules,
                "statusTimeouts": {"inactive": 10, "closed": 60},
            },
        },
    }
    if intelligence_config_id:
        body["intelligenceConfigurationIds"] = [intelligence_config_id]
    # Where the Orchestrator POSTs Conversation lifecycle events (inbound
    # SMS messages, status changes, etc.). Must be reachable from Twilio.
    voice_domain = os.environ.get("TWILIO_VOICE_PUBLIC_DOMAIN", "")
    if voice_domain:
        body["statusCallbacks"] = [
            {"url": f"https://{voice_domain}/webhook", "method": "POST"}
        ]
    return body


def ensure_orchestrator_config(
    memory_store_id: str, intelligence_config_id: str, force: bool
) -> str:
    sid = os.getenv("TWILIO_CONVERSATION_CONFIGURATION_ID", "")

    # Twilio's Orchestrator API requires both `description` and
    # `memoryStoreId` (not optional despite what the API-ref table
    # implies). Abort cleanly if we have no Memory Store SID.
    if not memory_store_id:
        print(
            "  SKIP: cannot create Orchestrator Configuration without "
            "TWILIO_MEMORY_STORE_ID.\n"
            "  Enable Conversation Memory on the account and re-run "
            "provision.py, or set TWILIO_MEMORY_STORE_ID manually in .env.",
            file=sys.stderr,
        )
        return ""

    body = _orchestrator_body(memory_store_id, intelligence_config_id)

    if sid and not force and _exists(
        f"https://conversations.twilio.com/v2/ControlPlane/Configurations/{sid}"
    ):
        print(f"updating Orchestrator Configuration {sid}…")
        # PUT re-applies the full body so adding capture rules or
        # intelligence linkage retroactively works.
        r = httpx.put(
            f"https://conversations.twilio.com/v2/ControlPlane/Configurations/{sid}",
            auth=AUTH,
            json=body,
            timeout=30,
        )
        r.raise_for_status()
        return sid

    print("creating Orchestrator Configuration…")
    if not PHONE:
        print("  WARN: TWILIO_PHONE_NUMBER not set; capture rules will be left empty")

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
            "description": "voice-blueprint intelligence configuration",
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
    # Serialize the application/x-www-form-urlencoded body by hand so
    # repeated keys survive (httpx's dict-based form encoding collapses
    # them, which is what caused the h11 send-crash on the first version).
    from urllib.parse import urlencode

    body = urlencode(
        [
            ("Description", "voice-blueprint"),
            ("SinkSid", sink_sid),
            *(("Types", json.dumps(t)) for t in SUBSCRIPTION_TYPES),
        ]
    )
    r = httpx.post(
        "https://events.twilio.com/v1/Subscriptions",
        auth=AUTH,
        content=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if r.status_code >= 400:
        # Non-zero exit so operators (and CI) know the run didn't fully
        # succeed. Common cause: a Type name was wrong (20409) or the
        # Sink SID is stale (20404). The Twilio body usually names the
        # culprit — browse https://events.twilio.com/v1/Types for the
        # canonical catalog and edit SUBSCRIPTION_TYPES.
        print(
            f"  subscription create failed: {r.status_code} {r.text}\n"
            "  inspect https://events.twilio.com/v1/Types to reconcile "
            "and edit SUBSCRIPTION_TYPES in scripts/provision.py.",
            file=sys.stderr,
        )
        raise SystemExit(1)
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
    # Intelligence first so we can wire its ID into the Orchestrator Config.
    intel = ensure_intelligence_config(args.force)
    ensure_orchestrator_config(mem, intel, args.force)
    sink = ensure_event_streams_sink(args.force)
    ensure_event_streams_subscription(sink, args.force)
    print("done.")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as e:
        print(f"Twilio API error: {e.response.status_code} {e.response.text}", file=sys.stderr)
        raise
