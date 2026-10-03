import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    api_key: str = os.getenv("TWILIO_API_KEY", "")
    api_secret: str = os.getenv("TWILIO_API_SECRET", "")
    phone_number: str = os.getenv("TWILIO_PHONE_NUMBER", "")
    voice_public_domain: str = os.getenv("TWILIO_VOICE_PUBLIC_DOMAIN", "")
    memory_store_id: str = os.getenv("TWILIO_MEMORY_STORE_ID", "")
    conversation_configuration_id: str = os.getenv("TWILIO_CONVERSATION_CONFIGURATION_ID", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


settings = Settings()
