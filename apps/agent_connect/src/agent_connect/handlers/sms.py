from fastapi import APIRouter, Form
from fastapi.responses import Response
from twilio.twiml.messaging_response import MessagingResponse

router = APIRouter()


@router.post("/sms/inbound")
async def inbound_sms(From: str = Form(...), Body: str = Form(...)):
    """Twilio webhook for inbound SMS. TAC's SMSChannel will replace this stub."""
    mr = MessagingResponse()
    mr.message(f"Received: {Body}")
    return Response(content=str(mr), media_type="application/xml")
