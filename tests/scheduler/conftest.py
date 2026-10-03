"""Shared scheduler fixtures.

Each test gets a fresh temporary jobs.db + audit.db so SQLite state doesn't
leak between tests. The firing worker loop is disabled by default; opt in
with the `live_worker` fixture.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def temp_dbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    jobs = tmp_path / "jobs.db"
    audit = tmp_path / "audit.db"
    monkeypatch.setenv("JOBS_DB_PATH", str(jobs))
    monkeypatch.setenv("AUDIT_DB_PATH", str(audit))
    monkeypatch.setenv("DEV_MODE", "1")
    # Avoid firing to real Twilio or event-ingestor
    monkeypatch.setenv("EVENT_INGESTOR_URL", "")
    return {"jobs": str(jobs), "audit": str(audit)}


@pytest.fixture()
def _reload_settings(temp_dbs):
    """Reload every scheduler module that captures env vars at import time.

    FastAPI's app, settings, and the policy chain are all module-level
    singletons; without a reload the first test's state leaks into the
    second.
    """
    import importlib
    import sys

    # Drop every scheduler module so the test gets a clean import tree.
    for name in list(sys.modules):
        if name == "scheduler" or name.startswith("scheduler."):
            del sys.modules[name]
    # Also drop the policy's module-level DNC reference.
    yield
    for name in list(sys.modules):
        if name == "scheduler" or name.startswith("scheduler."):
            del sys.modules[name]
    _ = importlib  # keep import to silence linters
    os.environ.pop("JOBS_DB_PATH", None)
    os.environ.pop("AUDIT_DB_PATH", None)
