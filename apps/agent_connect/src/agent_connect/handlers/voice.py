from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, VoiceResponse

from agent_connect.config import settings

router = APIRouter()


@router.post("/voice/inbound")
async def inbound_twiml(req: Request):
    """TwiML returned to Twilio for inbound voice calls — hands off to ConversationRelay."""
    vr = VoiceResponse()
    connect = Connect()
    connect.conversation_relay(
        url=f"wss://{settings.voice_public_domain}/voice/ws",
        welcome_greeting="Hello, how can I help?",
        conversation_configuration=settings.conversation_configuration_id or None,
    )
    vr.append(connect)
    return Response(content=str(vr), media_type="application/xml")


@router.websocket("/voice/ws")
async def voice_ws(ws: WebSocket):
    """ConversationRelay WebSocket. Twilio handles STT/TTS; we exchange JSON."""
    await ws.accept()
    try:
        while True:
            event = await ws.receive_json()
            if event.get("type") == "prompt":
                reply = await _llm_reply(event["voicePrompt"])
                await ws.send_json({"type": "text", "token": reply, "last": True})
    except WebSocketDisconnect:
        return


async def _llm_reply(user_text: str) -> str:
    # TODO: wire TAC + OpenAI with Memory recall
    return f"You said: {user_text}"
