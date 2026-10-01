from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from voice_blueprint_shared.audit import AuditEvent, audit_record, open_audit_db
from voice_blueprint_shared.otel import init_otel

from event_ingestor.config import settings
from event_ingestor.routing import route_event
from event_ingestor.validation import verify_twilio_signature


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.audit_db = open_audit_db(settings.audit_db_path)
    yield
    app.state.audit_db.close()


app = FastAPI(title="event-ingestor", lifespan=lifespan)
init_otel("event-ingestor", app=app)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/twilio/events")
async def twilio_events(req: Request):
    body = await req.body()
    verify_twilio_signature(req, body)
    events = (await req.json()) if body else []
    if not isinstance(events, list):
        events = [events]

    processed = 0
    for ev in events:
        event_id = ev.get("event_id") or ev.get("sid") or ""
        if not _mark_seen(req.app.state.audit_db, event_id):
            continue
        audit_record(
            req.app.state.audit_db,
            AuditEvent(
                actor="twilio",
                action=ev.get("type", "unknown"),
                subject=event_id or "unknown",
                data=ev,
            ),
        )
        await route_event(ev)
        processed += 1

    return {"processed": processed}


def _mark_seen(conn, event_id: str) -> bool:
    if not event_id:
        return True
    try:
        conn.execute(
            "INSERT INTO seen_events (event_id, seen_at) VALUES (?, datetime('now'))",
            (event_id,),
        )
        return True
    except Exception:
        return False
