from fastapi import HTTPException, Request
from twilio.request_validator import RequestValidator

from event_ingestor.config import settings


def verify_twilio_signature(req: Request, body: bytes) -> None:
    """Raise 401 if the Twilio signature header is missing or invalid.

    Event Streams signs requests the same way as webhooks; the signature header
    is `X-Twilio-Signature` and the signed string is the full URL + sorted params
    (or raw body for JSON sinks).
    """
    sig = req.headers.get("X-Twilio-Signature")
    if not sig or not settings.auth_token:
        if not settings.auth_token:
            return  # dev mode: no token configured
        raise HTTPException(status_code=401, detail="missing signature")

    validator = RequestValidator(settings.auth_token)
    url = str(req.url)
    if not validator.validate(url, body.decode("utf-8"), sig):
        raise HTTPException(status_code=401, detail="invalid signature")
