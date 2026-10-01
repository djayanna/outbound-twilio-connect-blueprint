from fastapi import APIRouter, HTTPException, Request
from voice_blueprint_shared.audit import AuditEvent, audit_record
from voice_blueprint_shared.job import Job

from scheduler.jobs.lifecycle import accept_job
from scheduler.jobs.store import JobStore

router = APIRouter()


def store(req: Request) -> JobStore:
    return req.app.state.store


@router.post("/jobs", status_code=201)
async def create_job(job: Job, req: Request):
    decision = await accept_job(job, store(req))
    audit_record(
        req.app.state.audit_db,
        AuditEvent(
            actor="scheduler",
            action=f"job.{decision.outcome}",
            subject=job.id,
            data={"reason": decision.reason, "scheduled_for": str(job.scheduled_for)},
        ),
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


@router.get("/stats")
def stats(req: Request):
    return store(req).stats()


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
