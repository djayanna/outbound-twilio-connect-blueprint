"""agent-connect — TAC application entrypoint.

Composition:
  * The TAC SDK supplies the Twilio-facing surface — inbound TwiML, the
    ConversationRelay WebSocket, SMS webhook, Conversation Intelligence
    callbacks. It mounts those routes onto *our* FastAPI app via
    `TACFastAPIServer(app=app)` (constructor only — we don't call .start()
    since uvicorn is driven by the Procfile).
  * Our own `/outbound` endpoint stays as the entrypoint the scheduler
    POSTs Jobs to.
  * `on_message_ready` is the only "write LLM code" point: scenario-aware
    system prompt + OpenAI call wrapped with `with_tac_memory`.

If OPENAI_API_KEY is not set, the service still boots and TAC routes still
mount, but on_message_ready returns a stub reply (so smoke tests pass
without burning OpenAI credit).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from tac import TAC, TACConfig
from tac.adapters.openai import with_tac_memory
from tac.channels.sms import SMSChannel
from tac.channels.voice import VoiceChannel
from tac.models.session import ConversationSession
from tac.models.tac import TACMemoryResponse
from tac.server import TACFastAPIServer
from voice_blueprint_shared.otel import init_otel

from agent_connect.config import settings
from agent_connect.handlers import outbound
from agent_connect.prompts import get as get_scenario

log = logging.getLogger("agent_connect")


def _build_tac() -> tuple[TAC, VoiceChannel, SMSChannel] | None:
    """Construct TAC + channels. Returns None on failure.

    TAC validates its config against Twilio's API on construction (fetches the
    Conversation Orchestrator Configuration). When credentials are missing or
    the configuration SID is unknown we log and skip mounting TAC routes —
    the service still exposes /outbound and /health so the rest of the
    blueprint boots and `scripts/provision.py` can run.
    """
    try:
        tac = TAC(config=TACConfig.from_env())
    except Exception as exc:
        log.warning(
            "TAC not initialized (likely missing/invalid Twilio creds): %s. "
            "Run `uv run python scripts/provision.py` and populate .env.",
            exc,
        )
        return None
    return tac, VoiceChannel(tac), SMSChannel(tac)


def _scenario_from_context(context: ConversationSession) -> str:
    """Scenario travels in the Conversation attributes we set on outbound.

    Falls back to "default" so inbound (unprompted) conversations still work.
    """
    attrs = getattr(context, "attributes", None) or {}
    return attrs.get("scenario", "default")


async def _handle_message_ready(
    message: str,
    context: ConversationSession,
    memory: TACMemoryResponse | None,
) -> str | None:
    """LLM turn. Scenario-aware system prompt + Memory-wrapped OpenAI."""
    scenario = get_scenario(_scenario_from_context(context))

    if not settings.openai_api_key:
        log.warning("OPENAI_API_KEY not set; returning stub reply")
        return f"[{scenario.key}] (stub) You said: {message}"

    # Lazy-imported so the service boots even without the openai package
    # fully configured.
    from openai import AsyncOpenAI

    client = with_tac_memory(
        AsyncOpenAI(api_key=settings.openai_api_key),
        memory,
        context,
    )
    response = await client.responses.create(
        model=settings.openai_model,
        instructions=scenario.system_prompt,
        input=message,
    )
    return getattr(response, "output_text", None) or str(response)


app = FastAPI(title="agent-connect")
init_otel("agent-connect", app=app)
app.include_router(outbound.router)

_built = _build_tac()
if _built is not None:
    _tac, _voice, _sms = _built
    _tac.on_message_ready(_handle_message_ready)
    TACFastAPIServer(tac=_tac, voice_channel=_voice, messaging_channels=[_sms], app=app)


@app.get("/health")
def health():
    return {"status": "ok"}
