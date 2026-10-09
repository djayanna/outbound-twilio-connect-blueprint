import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from voice_blueprint_shared.audit import open_audit_db
from voice_blueprint_shared.otel import init_otel

from scheduler.config import settings
from scheduler.conversations.repository import ConversationStore, open_conversations_db
from scheduler.http import callbacks, conversation_events, conversations, routes
from scheduler.jobs.repository import SqliteJobRepository, open_jobs_db
from scheduler.jobs.store import JobStore
from scheduler.policy.dnc_repository import SqliteDncRepository
from scheduler.policy.suppression import set_dnc_repository
from scheduler.worker.loop import run_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.audit_db = open_audit_db(settings.audit_db_path)
    app.state.jobs_db = open_jobs_db(settings.jobs_db_path)
    app.state.conversations_db = open_conversations_db(settings.conversations_db_path)
    app.state.conversations = ConversationStore(app.state.conversations_db)
    app.state.store = JobStore(SqliteJobRepository(app.state.jobs_db))
    app.state.dnc = SqliteDncRepository(app.state.jobs_db)
    set_dnc_repository(app.state.dnc)
    app.state.worker_stop = asyncio.Event()
    app.state.worker_task = asyncio.create_task(
        run_loop(app.state.store, app.state.audit_db, stop_event=app.state.worker_stop),
        name="scheduler-worker",
    )
    try:
        yield
    finally:
        app.state.worker_stop.set()
        try:
            await asyncio.wait_for(app.state.worker_task, timeout=5)
        except TimeoutError:
            app.state.worker_task.cancel()
        app.state.jobs_db.close()
        app.state.conversations_db.close()
        app.state.audit_db.close()


app = FastAPI(title="scheduler", lifespan=lifespan)
init_otel("scheduler", app=app)
app.include_router(routes.router)
app.include_router(callbacks.router)
app.include_router(conversation_events.router)
app.include_router(conversations.router)


@app.get("/health")
def health():
    return {"status": "ok"}
