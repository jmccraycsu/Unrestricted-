from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str
    openai_api_key: str

    self_hosted_base_url: str | None = None
    self_hosted_api_key: str = "unused"
    self_hosted_model: str = "default"

    hive_api_key: str | None = None
    sightengine_api_user: str | None = None
    sightengine_api_secret: str | None = None

    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/generation"
    redis_url: str = "redis://redis:6379/0"

    max_retries_per_provider: int = 2


@lru_cache
def get_settings() -> Settings:
    # Lazy + cached: importing this module never fails just because env
    # vars aren't set yet; the error only surfaces when settings are
    # actually needed (first real request/worker start), with a clear
    # message about which var is missing.
    return Settings()
