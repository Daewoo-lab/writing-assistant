from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://wa:wa@localhost:5432/wa"
    redis_url: str = "redis://localhost:6379/0"

    telegram_bot_token: str = ""

    anthropic_api_key: str = ""
    anthropic_base_url: str | None = None
    llm_model: str = "claude-opus-4-8"

    payme_merchant_id: str = ""
    payme_secret_key: str = ""
    payme_login_for_callbacks: str = "Paycom"

    web_base_url: str = "http://localhost:8000"


settings = Settings()
