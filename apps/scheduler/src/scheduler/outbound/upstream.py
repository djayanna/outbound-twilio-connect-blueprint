"""Signed POSTs to the Job's `upstream_callback_url`.

Shape of each payload mirrors the audit event:
    {at, actor, action, subject, data}

Signature is HMAC-SHA256 over the raw request body using
`UPSTREAM_CALLBACK_SIGNING_KEY`, placed in `X-Blueprint-Signature`.
Verify downstream the same way:

    import hmac, hashlib
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    hmac.compare_digest(expected, signature)

Delivery is best-effort — the audit log is still the source of truth.
Failures are logged, never raised.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

import httpx
from voice_blueprint_shared.job import Job

from scheduler.config import settings

log = logging.getLogger("scheduler.upstream")


def notify_upstream(job: Job, action: str, data: dict) -> None:
    """Fire-and-forget POST to job.upstream_callback_url (if set)."""
    url = job.upstream_callback_url
    if not url:
        return
    payload = {
        "at": datetime.now(UTC).isoformat(),
        "actor": "scheduler",
        "action": action,
        "subject": job.id,
        "data": data,
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(_post(url, payload))
        except Exception as exc:
            log.warning("upstream notify failed (sync) for %s: %s", job.id, exc)
        return
    loop.create_task(_post(url, payload), name="upstream-notify")


async def _post(url: str, payload: dict) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {"content-type": "application/json"}
    secret = settings.upstream_signing_key.encode() if settings.upstream_signing_key else b""
    if secret:
        headers["X-Blueprint-Signature"] = hmac.new(secret, body, hashlib.sha256).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(url, content=body, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("upstream notify failed for %s: %s", url, exc)


__all__ = ["notify_upstream"]
