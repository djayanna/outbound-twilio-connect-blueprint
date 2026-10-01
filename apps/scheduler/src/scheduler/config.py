import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    audit_db_path: str = os.getenv("AUDIT_DB_PATH", "./data/audit.db")
    agent_connect_url: str = os.getenv("AGENT_CONNECT_URL", "http://localhost:3002")
    default_from: str = os.getenv("TWILIO_PHONE_NUMBER", "")


settings = Settings()
