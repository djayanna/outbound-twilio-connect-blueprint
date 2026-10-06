"""Do-Not-Contact policy check.

The repository is injected via a module-level reference (set in main.py's
lifespan). Keeping the policy function dependency-light makes the chain
in `scheduler.policy.check_all()` trivial to compose.
"""
from __future__ import annotations

from voice_blueprint_shared.job import Job

from scheduler.policy.dnc_repository import DncRepository

# Set by main.py during startup. Reads before set return "not on DNC" so
# unit tests that import policy modules in isolation don't need to wire a
# repo.
_repo: DncRepository | None = None


def set_dnc_repository(repo: DncRepository) -> None:
    global _repo
    _repo = repo


def check_suppression(job: Job):
    from scheduler.policy import Verdict

    if _repo is not None and _repo.contains(job.to):
        return Verdict(suppress=True, reason="do_not_contact")
    return Verdict(suppress=False)
