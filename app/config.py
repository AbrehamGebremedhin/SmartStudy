from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    deepseek_api_key: str
    google_client_id: str
    chat_session_ttl_hours: int = 24
    poppler_path: str | None = None

    model_config = {"env_file": ".env"}


settings = Settings()
