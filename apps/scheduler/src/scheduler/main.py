from contextlib import asynccontextmanager

from fastapi import FastAPI
from voice_blueprint_shared.audit import open_audit_db
from voice_blueprint_shared.otel import init_otel

from scheduler.config import settings
from scheduler.http import routes
from scheduler.jobs.repository import SqliteJobRepository, open_jobs_db
from scheduler.jobs.store import JobStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.audit_db = open_audit_db(settings.audit_db_path)
    app.state.jobs_db = open_jobs_db(settings.jobs_db_path)
    app.state.store = JobStore(SqliteJobRepository(app.state.jobs_db))
    yield
    app.state.jobs_db.close()
    app.state.audit_db.close()


app = FastAPI(title="scheduler", lifespan=lifespan)
init_otel("scheduler", app=app)
app.include_router(routes.router)


@app.get("/health")
def health():
    return {"status": "ok"}
