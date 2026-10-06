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

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response
from tac import TAC, TACConfig, VoiceTwiMLOptionsConversationRelay
from tac.adapters.openai import with_tac_memory
from tac.channels.sms import SMSChannel
from tac.channels.voice import VoiceChannel
from tac.models.session import ConversationSession
from tac.models.tac import TACMemoryResponse
from tac.models.voice import TwiMLRequest
from tac.server import TACFastAPIServer
from voice_blueprint_shared.otel import init_otel

from agent_connect.config import settings
from agent_connect.handlers import outbound
from agent_connect.prompts import get as get_scenario
from agent_connect.prompts import voicemail_prompt_for
from agent_connect.tools import SCENARIO_TOOLS, set_upstream_api_url

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


def _attrs(context: ConversationSession) -> dict:
    return getattr(context, "attributes", None) or {}


def _scenario_key(context: ConversationSession) -> str:
    """Scenario travels in the Conversation attributes we set on outbound.

    Falls back to "default" so inbound (unprompted) conversations still work.
    """
    return _attrs(context).get("scenario", "default")


def _instructions_with_context(system_prompt: str, job_context: dict) -> str:
    """Append the Job.context as a sanitized k=v block the LLM can reference."""
    if not job_context:
        return system_prompt
    lines = [f"- {k}: {v}" for k, v in job_context.items() if not k.startswith("_")]
    return system_prompt + "\n\nContext from the originating system:\n" + "\n".join(lines)


_MACHINE_ANSWERED = {"machine_start", "machine_end_beep", "machine_end_silence", "machine_end_other"}


async def _fetch_run_hint(call_sid: str | None) -> tuple[str | None, str | None, dict]:
    """Ask the scheduler for AMD verdict + Job metadata for this live call.

    Returns (answered_by, scenario, job_context). Everything defaults to
    None/{} if the scheduler is unreachable or the sid isn't known — in
    that case we behave as a generic agent (safest default).
    """
    if not call_sid or not settings.scheduler_internal_url:
        return None, None, {}
    url = f"{settings.scheduler_internal_url.rstrip('/')}/runs/by-sid/{call_sid}"
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(url)
        if r.status_code != 200:
            return None, None, {}
        body = r.json()
        run = body.get("run") or {}
        job = body.get("job") or {}
        return run.get("answered_by"), job.get("scenario"), (job.get("context") or {})
    except httpx.HTTPError:
        return None, None, {}


def _call_sid_from(context: ConversationSession) -> str | None:
    """Best-effort extraction of CallSid from the TAC session."""
    for attr in ("call_sid", "callSid", "communication_sid"):
        v = getattr(context, attr, None)
        if v:
            return v
    return _attrs(context).get("call_sid")


async def _handle_message_ready(
    message: str,
    context: ConversationSession,
    memory: TACMemoryResponse | None,
) -> str | None:
    """LLM turn. Scenario-aware system prompt + Memory-wrapped OpenAI + tools.

    AMD policy: if the scheduler recorded `answered_by=machine_*` for this
    call and the Job set `on_machine_answer=leave_voicemail`, we swap the
    scenario's conversational system prompt for its one-sentence voicemail
    persona.
    """
    attrs = _attrs(context)

    # Pull everything the scheduler knows about this call — scenario,
    # Job context, and AMD verdict (if any). Attributes on the TAC
    # ConversationSession aren't set by the current outbound path, so
    # the scheduler is the only source of scenario truth per-call.
    answered_by, hint_scenario, hint_ctx = await _fetch_run_hint(_call_sid_from(context))
    scenario_key = hint_scenario or _scenario_key(context)
    scenario = get_scenario(scenario_key)
    job_context = hint_ctx or (attrs.get("context") or {})

    is_voicemail = (
        answered_by in _MACHINE_ANSWERED
        and job_context.get("on_machine_answer") == "leave_voicemail"
    )

    # Make the upstream backend URL available to tool implementations.
    set_upstream_api_url(job_context.get("upstream_api_url"))

    if not settings.openai_api_key:
        log.warning("OPENAI_API_KEY not set; returning stub reply")
        tag = "voicemail" if is_voicemail else scenario.key
        return f"[{tag}] (stub) You said: {message}"

    from openai import AsyncOpenAI

    client = with_tac_memory(
        AsyncOpenAI(api_key=settings.openai_api_key),
        memory,
        context,
    )
    base_prompt = (
        voicemail_prompt_for(scenario.key) if is_voicemail else scenario.system_prompt
    )
    kwargs: dict = {
        "model": settings.openai_model,
        "instructions": _instructions_with_context(base_prompt, job_context),
        "input": message,
    }
    # Tools are useless in a one-shot voicemail — don't pass them.
    if not is_voicemail:
        tools = SCENARIO_TOOLS.get(scenario.key)
        if tools:
            kwargs["tools"] = [
                t.to_openai_tool() if hasattr(t, "to_openai_tool") else t for t in tools
            ]
    response = await client.responses.create(**kwargs)
    return getattr(response, "output_text", None) or str(response)


app = FastAPI(title="agent-connect")
init_otel("agent-connect", app=app)
app.include_router(outbound.router)

_built = _build_tac()
if _built is not None:
    _tac, _voice, _sms = _built
    _tac.on_message_ready(_handle_message_ready)

    # Register our scenario-aware /twiml BEFORE TACFastAPIServer so our
    # route wins the match. We call back into TAC's VoiceChannel to do
    # the heavy lifting; we only override the welcome_greeting.
    # /twiml is TACServerConfig.twiml_path's default — override via
    # TACServerConfig if you ever customize the path.
    @app.post("/twiml")
    async def scenario_twiml(request: Request) -> Response:
        form = await request.form()
        form_dict = {k: v for k, v in form.items() if isinstance(v, str)}
        twiml_request = TwiMLRequest.from_form(form_dict)
        call_sid = form_dict.get("CallSid")
        _, hint_scenario, hint_ctx = await _fetch_run_hint(call_sid)
        scenario = get_scenario(hint_scenario or "default")
        welcome = _render_welcome(scenario.voice_welcome, hint_ctx)
        twiml = await _voice.handle_incoming_call(
            twiml_request=twiml_request,
            host_twiml_options=VoiceTwiMLOptionsConversationRelay(welcome_greeting=welcome),
        )
        return Response(content=twiml, media_type="application/xml")

    TACFastAPIServer(tac=_tac, voice_channel=_voice, messaging_channels=[_sms], app=app)


def _render_welcome(welcome: str, job_context: dict) -> str:
    """Format {placeholders} in the voice_welcome against job_context.

    Missing keys fall back to the raw template so the call still goes
    through even when context is sparse.
    """
    if not welcome:
        return welcome
    try:
        return welcome.format(**job_context)
    except (KeyError, IndexError):
        return welcome


@app.get("/health")
def health():
    return {"status": "ok"}
