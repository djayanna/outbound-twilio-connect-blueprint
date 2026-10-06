"""Outbound initiation.

The scheduler POSTs a Job here; we call Twilio's REST API to place the call
or send the message, and arrange for status callbacks to flow back to the
scheduler. The TwiML URL points at TAC's /twiml handler mounted on the
same app.

AMD (Answering Machine Detection)
---------------------------------
Every outbound voice call ships with `machine_detection="DetectMessageEnd"`
and an async AMD callback pointing at the scheduler's /twilio/amd endpoint.
What the scheduler DOES with that detection depends on the Job:

  job.context.on_machine_answer = "hangup"           (default)
                                | "leave_voicemail"

See `scheduler/http/callbacks.py:twilio_amd` for the policy switch and
`agent_connect/prompts/__init__.py:Scenario.on_machine_answer` for the
scenario-level default.
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


def _scheduler_url(path: str) -> str | None:
    base = settings.scheduler_public_url.rstrip("/")
    return f"{base}{path}" if base else None


@router.post("/outbound")
async def outbound(job: Job):
    """Initiate an outbound SMS or voice call for this Job."""
    client = _twilio_client()
    from_ = job.from_ or settings.phone_number
    status_cb = _scheduler_url("/twilio/status")
    amd_cb = _scheduler_url("/twilio/amd")

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
        # Run AMD in parallel with the greeting so humans don't wait 2–6 s.
        "machine_detection": "DetectMessageEnd",
        "async_amd": "true",
    }
    if status_cb:
        kwargs["status_callback"] = status_cb
        kwargs["status_callback_event"] = _VOICE_STATUS_EVENTS
        kwargs["status_callback_method"] = "POST"
    if amd_cb:
        kwargs["async_amd_status_callback"] = amd_cb
        kwargs["async_amd_status_callback_method"] = "POST"
    call = client.calls.create(**kwargs)
    return {"twilio_call_sid": call.sid}
