from fastapi import APIRouter
from twilio.rest import Client
from voice_blueprint_shared.job import Job

from agent_connect.config import settings

router = APIRouter()


def _twilio_client() -> Client:
    return Client(settings.account_sid, settings.auth_token)


@router.post("/outbound")
async def outbound(job: Job):
    """Initiate an outbound SMS or voice call for this Job."""
    client = _twilio_client()
    from_ = job.from_ or settings.phone_number

    if job.channel == "sms":
        msg = client.messages.create(
            to=job.to,
            from_=from_,
            body=f"[{job.scenario}] This is a sample outbound message.",
        )
        return {"twilio_message_sid": msg.sid}

    # voice: point the inbound TwiML endpoint; ConversationRelay takes over on answer
    call = client.calls.create(
        to=job.to,
        from_=from_,
        url=f"https://{settings.voice_public_domain}/voice/inbound",
    )
    return {"twilio_call_sid": call.sid}
