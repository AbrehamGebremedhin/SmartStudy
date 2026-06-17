import re

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    deepseek_api_key: str
    google_client_id: str
    secret_key: str
    chat_session_ttl_hours: int = 24
    app_token_expire_days: int = 30
    poppler_path: str | None = None
    allowed_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Gemini keys for the exam-question enrichment job. Each MUST come from a
    # separate Google Cloud project (free-tier quota is per-project, not per-key).
    gemini_api_key_1: str | None = None
    gemini_api_key_2: str | None = None
    gemini_api_key_3: str | None = None
    gemini_api_key_4: str | None = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def gemini_api_keys(self) -> list[str]:
        """Non-empty Gemini keys, in order. Used by the enrichment key-rotation pool."""
        return [
            k for k in (
                self.gemini_api_key_1, self.gemini_api_key_2,
                self.gemini_api_key_3, self.gemini_api_key_4,
            )
            if k and k.strip()
        ]

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not re.match(r"^postgresql(\+\w+)?://", v):
            raise ValueError("DATABASE_URL must be a valid PostgreSQL connection string (postgresql://...)")
        return v

    @field_validator("deepseek_api_key")
    @classmethod
    def validate_deepseek_api_key(cls, v: str) -> str:
        if not v.startswith("sk-") or len(v) < 20:
            raise ValueError("DEEPSEEK_API_KEY appears invalid — must start with 'sk-' and be at least 20 characters")
        return v

    @field_validator("google_client_id")
    @classmethod
    def validate_google_client_id(cls, v: str) -> str:
        if not v.endswith(".apps.googleusercontent.com"):
            raise ValueError("GOOGLE_CLIENT_ID must end with '.apps.googleusercontent.com'")
        return v

    @field_validator("chat_session_ttl_hours")
    @classmethod
    def validate_ttl(cls, v: int) -> int:
        if v < 1 or v > 8760:
            raise ValueError("CHAT_SESSION_TTL_HOURS must be between 1 and 8760 (1 year)")
        return v

    @model_validator(mode="after")
    def check_no_placeholder_values(self) -> "Settings":
        placeholders = {"your-", "xxxx", "replace", "changeme", "placeholder"}
        checks = {
            "DEEPSEEK_API_KEY": self.deepseek_api_key,
            "GOOGLE_CLIENT_ID": self.google_client_id,
        }
        for name, value in checks.items():
            if any(p in value.lower() for p in placeholders):
                raise ValueError(f"{name} looks like a placeholder — set a real value in your .env file")
        return self


settings = Settings()
