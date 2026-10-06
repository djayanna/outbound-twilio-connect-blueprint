"""Quiet-hours check in the recipient's local timezone.

Timezone resolution order:
  1. `job.constraints.timezone` (IANA, e.g. "America/Chicago")
  2. Country code of `job.to` via `scheduler.policy.timezones`
  3. UTC fallback

If no `allowed_hours_local` is configured on the Job's constraints, the
check is a no-op.
"""
from __future__ import annotations

from datetime import UTC, datetime, time

from voice_blueprint_shared.job import Job

from scheduler.policy.timezones import resolve_zone


def check_quiet_hours(job: Job):
    from scheduler.policy import Verdict

    c = job.constraints
    if not c or not c.allowed_hours_local:
        return Verdict(suppress=False)

    zone = resolve_zone(job.to, override=c.timezone)
    local_now = datetime.now(UTC).astimezone(zone).time()

    start = _parse_hhmm(c.allowed_hours_local[0])
    end = _parse_hhmm(c.allowed_hours_local[1])

    allowed = (
        start <= local_now <= end
        if start <= end
        # Window crosses midnight (e.g. 22:00–08:00): allowed means either leg.
        else local_now >= start or local_now <= end
    )
    if allowed:
        return Verdict(suppress=False)
    return Verdict(
        suppress=True,
        reason=f"outside_allowed_hours:{local_now.strftime('%H:%M')}@{zone.key}",
    )


def _parse_hhmm(s: str) -> time:
    return datetime.strptime(s, "%H:%M").time()
