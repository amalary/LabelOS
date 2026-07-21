import os
from functools import lru_cache

from pydantic import BaseModel, field_validator


class Settings(BaseModel):
    app_name: str = "Label OS Agents"
    app_version: str = "0.0.0"
    environment: str = "local"
    host: str = "0.0.0.0"
    port: int = 4100
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    model_provider: str = "mock"
    model_name: str = "mock-deterministic"
    model_timeout_seconds: int = 30
    require_human_approval: bool = True

    @field_validator("model_provider")
    @classmethod
    def normalize_model_provider(cls, value: str) -> str:
        return value.strip().lower()

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in {"local", "development", "dev", "test"}


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@lru_cache
def get_settings() -> Settings:
    return Settings(
        environment=os.getenv("APP_ENV", "local"),
        host=os.getenv("AGENTS_HOST", "0.0.0.0"),
        port=int(os.getenv("AGENTS_PORT", "4100")),
        log_level=os.getenv("AGENTS_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO")),
        model_provider=os.getenv("AGENTS_MODEL_PROVIDER", "mock"),
        model_name=os.getenv("AGENTS_MODEL_NAME", "mock-deterministic"),
        model_timeout_seconds=int(os.getenv("AGENTS_MODEL_TIMEOUT_SECONDS", "30")),
        require_human_approval=_get_bool("AGENTS_REQUIRE_HUMAN_APPROVAL", True),
    )
