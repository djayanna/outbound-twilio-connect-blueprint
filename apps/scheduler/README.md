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

## Core concepts

### Job vs JobRun

A **Job** is the business intent — "contact this customer at this time for this reason." It's immutable once accepted.

A **JobRun** is one execution attempt. Retries create new JobRuns against the same Job.

```python
class Job(BaseModel):
    id: str
    direction: Literal['outbound', 'inbound-followup']
    channel: Literal['voice', 'sms']
    to: str                           # E.164
    from_: str | None = None          # which Twilio number; scheduler picks default if None
    scheduled_for: datetime | Literal['now']
    scenario: str                     # key into prompts/ and tools/
    context: dict[str, Any] = {}
    consent: Consent | None = None
    constraints: Constraints | None = None
    retry_policy: RetryPolicy | None = None
    upstream_callback_url: str | None = None   # scheduler POSTs job lifecycle events here

class JobRun(BaseModel):
    job_id: str
    attempt: int
    status: Literal['pending', 'queued', 'in-progress', 'completed', 'failed', 'suppressed']
    conversation_id: str | None = None       # Twilio Orchestrator Conversation
    profile_id: str | None = None            # Twilio Memory Profile
    twilio_call_sid: str | None = None
    twilio_message_sid: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    terminal_reason: str | None = None
```

**Note:** `conversation_id` lives on `JobRun`, not `Job`. The Conversation is Twilio-side state created when the Job fires; it's not part of the business intent.

**`upstream_callback_url`** is an optional URL the scheduler POSTs to as the Job progresses — accepted/suppressed, each JobRun transition, terminal outcome. The upstream app that created the Job uses it to track status without polling. Shape of the POST body mirrors the audit event (`actor`, `action`, `subject`, `data`, `timestamp`).

### Example `jobs.json`

What upstream apps (or the test-harness) POST to `scheduler /jobs`. Full file at `examples/jobs/jobs.sample.json`.

```json
{
  "jobs": [
    {
      "id": "job-0001",
      "direction": "outbound",
      "channel": "sms",
      "to": "+15551110001",
      "scheduled_for": "now",
      "scenario": "appointment-confirmation",
      "context": { "appointment_time": "2026-10-05T15:00:00Z" },
      "upstream_callback_url": "https://crm.example.com/twilio/jobs/job-0001/events"
    },
    {
      "id": "job-0002",
      "direction": "outbound",
      "channel": "voice",
      "to": "+15551110002",
      "scheduled_for": "now",
      "scenario": "payment-reminder",
      "context": { "amount_due": "249.00", "due_date": "2026-10-10" },
      "retry_policy": { "max_attempts": 2, "backoff_seconds": 300 },
      "upstream_callback_url": "https://billing.example.com/webhooks/twilio-jobs"
    },
    {
      "id": "job-0003",
      "direction": "outbound",
      "channel": "sms",
      "to": "+15551110003",
      "scheduled_for": "now",
      "scenario": "promotion",
      "context": {},
      "consent": { "source": "web-signup", "captured_at": "2026-09-01T12:00:00Z" },
      "upstream_callback_url": "https://marketing.example.com/campaigns/callbacks"
    }
  ]
}
```
