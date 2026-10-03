from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Direction = Literal["outbound", "inbound-followup"]
Channel = Literal["voice", "sms"]
JobStatus = Literal["accepted", "scheduled", "firing", "done", "cancelled"]
RunStatus = Literal[
    "pending", "queued", "in-progress", "completed", "failed", "suppressed"
]


class Consent(BaseModel):
    source: str
    captured_at: datetime


class Constraints(BaseModel):
    allowed_hours_local: tuple[str, str] | None = None
    do_not_contact_before: datetime | None = None


class RetryPolicy(BaseModel):
    max_attempts: int = 3
    backoff_seconds: int = 60


class Job(BaseModel):
    id: str
    direction: Direction = "outbound"
    channel: Channel
    to: str
    from_: str | None = Field(default=None, alias="from")
    scheduled_for: datetime | Literal["now"] = "now"
    scenario: str
    context: dict[str, Any] = Field(default_factory=dict)
    consent: Consent | None = None
    constraints: Constraints | None = None
    retry_policy: RetryPolicy | None = None
    upstream_callback_url: str | None = None
    status: JobStatus = "accepted"

    model_config = {"populate_by_name": True}


class JobRun(BaseModel):
    job_id: str
    attempt: int = 1
    status: RunStatus = "pending"
    conversation_id: str | None = None
    profile_id: str | None = None
    twilio_call_sid: str | None = None
    twilio_message_sid: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    terminal_reason: str | None = None
