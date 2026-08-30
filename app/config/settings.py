from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://opspilot:opspilot@localhost:5432/opspilot"
    llm_provider: str = "anthropic"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4.1-mini"
    approval_secret: str = Field(
        default="development-only-secret-change-me-now",
        min_length=32,
    )
    approval_ttl_seconds: int = 300
    audit_log_path: Path = Path("audit/events.jsonl")


@lru_cache
def get_settings() -> Settings:
    return Settings()
