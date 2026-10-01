from fastapi import FastAPI
from voice_blueprint_shared.otel import init_otel

from agent_connect.handlers import outbound, sms, voice

app = FastAPI(title="agent-connect")
init_otel("agent-connect", app=app)

app.include_router(voice.router)
app.include_router(sms.router)
app.include_router(outbound.router)


@app.get("/health")
def health():
    return {"status": "ok"}
