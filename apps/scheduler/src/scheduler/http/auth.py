"""Shared-secret header auth for scheduler write endpoints.

Simplest thing that could work: a static key compared with hmac.compare_digest.
Set `BLUEPRINT_API_KEY` in the environment and pass it in `X-Blueprint-Key`
on every call to a protected route.

Rotation: change the env + restart. No DB story in the quickstart tier.

Dev bypass: if the env var is unset AND `DEV_MODE=1`, auth is skipped so
`honcho start` + the test harness just work. Any other combination
rejects (unset key in prod is a 500, not a silent pass).
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from scheduler.config import settings


def require_api_key(
    x_blueprint_key: str | None = Header(default=None, alias="X-Blueprint-Key"),
) -> None:
    expected = settings.api_key
    if not expected:
        if settings.dev_mode:
            return
        raise HTTPException(status_code=500, detail="BLUEPRINT_API_KEY not configured")
    if not x_blueprint_key or not hmac.compare_digest(x_blueprint_key, expected):
        raise HTTPException(status_code=401, detail="invalid or missing X-Blueprint-Key")
