# scheduler

Owns Jobs, JobRuns, audit.db, and all business policy. Scheduling and firing live here.

Run: `uv run uvicorn scheduler.main:app --port 3001 --reload`

Routes:
- `POST /jobs` — create a Job, runs policy, decides accept/suppress
- `GET /jobs` — list
- `GET /jobs/{id}` — detail + runs
- `GET /stats` — queue + in-flight for wallboard
- `GET /audit` — tail of audit log
- `GET /health`
