from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from voice_blueprint_shared.audit import AuditEvent, audit_record
from voice_blueprint_shared.job import Job

from scheduler.http.auth import require_api_key
from scheduler.jobs.lifecycle import accept_job
from scheduler.jobs.store import JobStore
from scheduler.outbound.notify import record_and_notify
from scheduler.policy.dnc_repository import DncRepository

router = APIRouter()


class DncRequest(BaseModel):
    phone: str
    reason: str | None = None


def store(req: Request) -> JobStore:
    return req.app.state.store


def _dnc(req: Request) -> DncRepository:
    return req.app.state.dnc


@router.post("/jobs", status_code=201, dependencies=[Depends(require_api_key)])
async def create_job(job: Job, req: Request):
    existing = store(req).get_job(job.id)
    if existing is not None:
        record_and_notify(
            req.app.state.audit_db,
            actor="scheduler",
            action="job.duplicate",
            job=existing,
            subject=job.id,
            data={"existing_status": existing.status},
        )
        return {
            "job": existing.model_dump(by_alias=True),
            "decision": {"outcome": "duplicate", "reason": "job_id_already_submitted"},
        }

    decision = await accept_job(job, store(req))
    record_and_notify(
        req.app.state.audit_db,
        actor="scheduler",
        action=f"job.{decision.outcome}",
        job=job,
        subject=job.id,
        data={"reason": decision.reason, "scheduled_for": str(job.scheduled_for)},
    )
    return {"job": job.model_dump(by_alias=True), "decision": decision.model_dump()}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, req: Request):
    job = store(req).get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {"job": job.model_dump(by_alias=True), "runs": [r.model_dump() for r in store(req).runs_for(job_id)]}


@router.get("/jobs")
def list_jobs(req: Request, status: str | None = None):
    jobs = store(req).list_jobs(status=status)
    return {"jobs": [j.model_dump(by_alias=True) for j in jobs]}


@router.get("/runs")
def list_runs(
    req: Request,
    job_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
):
    runs = store(req).list_runs(job_id=job_id, status=status, limit=limit)
    return {"runs": [r.model_dump() for r in runs]}


@router.get("/runs/{run_id}")
def get_run(run_id: int, req: Request):
    run = store(req).get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return {"run": run.model_dump()}


@router.get("/runs/by-sid/{sid}")
def get_run_by_sid(sid: str, req: Request):
    """Lookup used by agent-connect before each LLM turn to pick up the AMD verdict."""
    run = store(req).run_by_twilio_sid(sid)
    if not run:
        raise HTTPException(404, "run not found")
    job = store(req).get_job(run.job_id)
    return {
        "run": run.model_dump(),
        "job": job.model_dump(by_alias=True) if job else None,
    }


@router.get("/stats")
def stats(req: Request):
    return store(req).stats()


@router.get("/stats/queues")
def queue_depth(req: Request):
    return {"by_scenario": store(req).queue_depth_by_scenario()}


@router.get("/stats/lines")
def line_usage(req: Request):
    return {"by_from": store(req).line_usage()}


@router.get("/dnc")
def dnc_list(req: Request):
    return {"entries": _dnc(req).list()}


@router.post("/dnc", status_code=201, dependencies=[Depends(require_api_key)])
def dnc_add(body: DncRequest, req: Request):
    _dnc(req).add(body.phone, body.reason)
    audit_record(
        req.app.state.audit_db,
        AuditEvent(actor="ops", action="dnc.added", subject=body.phone,
                   data={"reason": body.reason}),
    )
    return {"phone": body.phone, "reason": body.reason}


@router.delete("/dnc/{phone}", dependencies=[Depends(require_api_key)])
def dnc_remove(phone: str, req: Request):
    removed = _dnc(req).remove(phone)
    if not removed:
        raise HTTPException(404, "number not on dnc")
    audit_record(
        req.app.state.audit_db,
        AuditEvent(actor="ops", action="dnc.removed", subject=phone, data={}),
    )
    return {"phone": phone, "removed": True}


@router.get("/audit")
def audit(req: Request, limit: int = 200):
    cur = req.app.state.audit_db.execute(
        "SELECT at, actor, action, subject, data FROM audit ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = [
        {"at": at, "actor": actor, "action": action, "subject": subject, "data": data}
        for at, actor, action, subject, data in cur.fetchall()
    ]
    return {"events": rows}
