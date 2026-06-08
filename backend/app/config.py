from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    deepseek_api_key: str
    google_client_id: str
    chat_session_ttl_hours: int = 24
    poppler_path: str | None = None
    allowed_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
