"""Verify Twilio-signed webhook requests.

Twilio Event Streams webhook sinks (what `scripts/provision.py` creates) sign
the request differently from a form-encoded Twilio webhook:

  * Form webhook: signature = HMAC-SHA1(URL + sorted key/value pairs)
  * JSON sink   : signature = HMAC-SHA1(URL) — the body isn't part of the
                  signed string. `validator.validate(url, "", sig)` is the
                  correct call shape.

Dev bypass: if `TWILIO_AUTH_TOKEN` is empty, verification is skipped only
when `DEV_MODE=1`. In any other combination (missing token in prod, missing
header, bad header) we return 401/500 — prod can't accidentally skip the
check by forgetting to set the token.
"""
from fastapi import HTTPException, Request
from twilio.request_validator import RequestValidator

from event_ingestor.config import settings


def verify_twilio_signature(req: Request, _body: bytes) -> None:
    sig = req.headers.get("X-Twilio-Signature")
    token = settings.auth_token

    if not token:
        if settings.dev_mode:
            return
        raise HTTPException(status_code=500, detail="auth token not configured")

    if not sig:
        raise HTTPException(status_code=401, detail="missing signature")

    validator = RequestValidator(token)
    # JSON sinks sign the URL alone; the body isn't included.
    if not validator.validate(str(req.url), "", sig):
        raise HTTPException(status_code=401, detail="invalid signature")
