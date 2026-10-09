import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    audit_db_path: str = os.getenv("AUDIT_DB_PATH", "./data/audit.db")
    jobs_db_path: str = os.getenv("JOBS_DB_PATH", "./data/jobs.db")
    conversations_db_path: str = os.getenv(
        "CONVERSATIONS_DB_PATH", "./data/conversations.db"
    )
    agent_connect_url: str = os.getenv("AGENT_CONNECT_URL", "http://localhost:3002")
    default_from: str = os.getenv("TWILIO_PHONE_NUMBER", "")
    auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    dev_mode: bool = os.getenv("DEV_MODE", "0") == "1"
    dedupe_window_seconds: int = int(os.getenv("DEDUPE_WINDOW_SECONDS", "3600"))
    concurrency_per_scenario: int = int(os.getenv("CONCURRENCY_PER_SCENARIO", "10"))
    upstream_signing_key: str = os.getenv("UPSTREAM_CALLBACK_SIGNING_KEY", "")
    api_key: str = os.getenv("BLUEPRINT_API_KEY", "")


settings = Settings()
