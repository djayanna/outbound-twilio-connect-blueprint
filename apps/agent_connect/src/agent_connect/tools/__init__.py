"""Function tools exposed to the LLM.

Three TAC `function_tool` definitions. Each stubs a call out to an
upstream system (CRM / billing / scheduling backend) via
`job.context["upstream_api_url"]`, so the blueprint is pluggable without
extra scaffolding:

  - lookup_account    — fetch the caller's account summary
  - schedule_callback — ask the backend to schedule a human callback
  - transfer          — hand the conversation to a human agent

TAC's `function_tool` decorator produces a `TACTool`. The per-scenario
tool bundle in `SCENARIO_TOOLS` lets the on_message_ready callback pick
the right set.

Each tool reads the upstream URL from a module-level variable set at
turn time via `set_upstream_api_url()` — the TAC tool-call protocol
doesn't thread the Job context into the tool invocation, so we stash it
on the module. Fine for a single-process reference app; swap for a
contextvar if you run multiple conversations in parallel.
"""
from __future__ import annotations

import contextvars

import httpx
from tac.tools import function_tool

_TIMEOUT = 10
_upstream_api_url: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "upstream_api_url", default=None
)


def set_upstream_api_url(url: str | None) -> None:
    """Call before a turn to bind the upstream backend URL for this task."""
    _upstream_api_url.set(url)


def _base() -> str | None:
    return _upstream_api_url.get()


@function_tool(description="Look up the caller's account summary from the upstream system.")
async def lookup_account(account_id: str) -> dict:
    """Fetch summary fields for the caller's account.

    Args:
        account_id: Account identifier.
    """
    url = _base()
    if not url:
        return {"ok": False, "reason": "upstream_api_url not configured"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(f"{url.rstrip('/')}/accounts/{account_id}")
    body = r.json() if r.is_success else None
    return {"ok": r.is_success, "status": r.status_code, "body": body}


@function_tool(description="Schedule a human-to-caller callback at the requested time.")
async def schedule_callback(account_id: str, when_iso: str, reason: str | None = None) -> dict:
    """Record a callback request on the upstream system.

    Args:
        account_id: Account identifier.
        when_iso:   ISO-8601 timestamp for the callback.
        reason:     Optional free-form reason.
    """
    url = _base()
    if not url:
        return {"ok": False, "reason": "upstream_api_url not configured"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(
            f"{url.rstrip('/')}/callbacks",
            json={"account_id": account_id, "when": when_iso, "reason": reason},
        )
    return {"ok": r.is_success, "status": r.status_code}


@function_tool(
    description="Transfer the current conversation to a human agent on the specified queue."
)
async def transfer(queue: str, note: str | None = None) -> dict:
    """Open a transfer ticket on the upstream system.

    Args:
        queue: Routing queue (e.g. "billing", "retention").
        note:  Optional handoff note.
    """
    url = _base()
    if not url:
        return {"ok": False, "reason": "upstream_api_url not configured"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{url.rstrip('/')}/transfers", json={"queue": queue, "note": note})
    return {"ok": r.is_success, "status": r.status_code}


# Per-scenario tool bundles. Scenarios opt in by key.
SCENARIO_TOOLS: dict[str, list] = {
    "appointment-confirmation": [schedule_callback, transfer],
    "payment-reminder": [lookup_account, schedule_callback, transfer],
    "promotion": [transfer],
}


__all__ = [
    "lookup_account",
    "schedule_callback",
    "transfer",
    "SCENARIO_TOOLS",
    "set_upstream_api_url",
]
