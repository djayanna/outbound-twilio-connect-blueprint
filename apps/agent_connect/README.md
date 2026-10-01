# agent-connect

The TAC application. Hosts inbound SMS webhook, ConversationRelay WebSocket, and outbound initiation endpoint.

Run: `uv run uvicorn agent_connect.main:app --port 3002 --reload`

Routes:
- `POST /voice/inbound` — TwiML for inbound voice (points at ConversationRelay)
- `WS   /voice/ws` — ConversationRelay WebSocket (STT/TTS by Twilio; LLM here)
- `POST /sms/inbound` — Twilio webhook for inbound SMS
- `POST /outbound` — called by scheduler to fire a Job
- `GET  /health`

The current implementation is a thin skeleton. Wiring the real TAC SDK
(`twilio-agent-connect`) replaces the handlers in `handlers/voice.py` and
`handlers/sms.py` with TAC's `VoiceChannel` + `SMSChannel`, and the LLM reply
with `on_message_ready`.
