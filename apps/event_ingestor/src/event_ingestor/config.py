import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    scheduler_url: str = os.getenv("SCHEDULER_URL", "http://localhost:3001")
    audit_db_path: str = os.getenv("AUDIT_DB_PATH", "./data/audit.db")
    dev_mode: bool = os.getenv("DEV_MODE", "0") == "1"
    scheduler_api_key: str = os.getenv("BLUEPRINT_API_KEY", "")


settings = Settings()
