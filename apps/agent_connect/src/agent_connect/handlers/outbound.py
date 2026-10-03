"""Outbound initiation.

The scheduler POSTs a Job here; we call Twilio's REST API to place the call
or send the message, and arrange for status callbacks to flow back to the
scheduler. The TwiML URL points at TAC's /twiml handler mounted on the
same app.
"""
from __future__ import annotations

from fastapi import APIRouter
from twilio.rest import Client
from voice_blueprint_shared.job import Job

from agent_connect.config import settings
from agent_connect.prompts import render_sms

router = APIRouter()

# Keep CR + SMS statuses in sync with the translation table in
# scheduler.http.callbacks._STATUS_MAP.
_VOICE_STATUS_EVENTS = ["initiated", "ringing", "answered", "completed"]


def _twilio_client() -> Client:
    return Client(settings.account_sid, settings.auth_token)


def _status_callback_url() -> str | None:
    base = settings.scheduler_public_url.rstrip("/")
    return f"{base}/twilio/status" if base else None


@router.post("/outbound")
async def outbound(job: Job):
    """Initiate an outbound SMS or voice call for this Job."""
    client = _twilio_client()
    from_ = job.from_ or settings.phone_number
    status_cb = _status_callback_url()

    if job.channel == "sms":
        kwargs: dict = {
            "to": job.to,
            "from_": from_,
            "body": render_sms(job.scenario, job.context),
        }
        if status_cb:
            kwargs["status_callback"] = status_cb
        msg = client.messages.create(**kwargs)
        return {"twilio_message_sid": msg.sid}

    # voice: TAC owns /twiml; ConversationRelay takes over on answer.
    kwargs = {
        "to": job.to,
        "from_": from_,
        "url": f"https://{settings.voice_public_domain}/twiml",
    }
    if status_cb:
        kwargs["status_callback"] = status_cb
        kwargs["status_callback_event"] = _VOICE_STATUS_EVENTS
        kwargs["status_callback_method"] = "POST"
    call = client.calls.create(**kwargs)
    return {"twilio_call_sid": call.sid}
