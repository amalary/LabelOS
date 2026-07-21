import os
from functools import lru_cache

from labelos_database.config import DatabaseSettings
from pydantic import Field, field_validator


class Settings(DatabaseSettings):
    app_name: str = "Label OS API"
    app_version: str = "0.0.0"
    environment: str = "local"
    api_host: str = "0.0.0.0"
    api_port: int = 4000
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    allowed_frontend_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
    )
    auth_provider: str = "oidc"
    auth_issuer_url: str | None = None
    auth_audience: str | None = None
    auth_jwt_algorithms: list[str] = Field(default_factory=lambda: ["HS256"])
    auth_token_secret: str | None = None

    @field_validator("allowed_frontend_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("auth_jwt_algorithms", mode="before")
    @classmethod
    def parse_auth_algorithms(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [
                algorithm.strip() for algorithm in value.split(",") if algorithm.strip()
            ]
        return value

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in {"local", "development", "dev"}


@lru_cache
def get_settings() -> Settings:
    return Settings(
        environment=os.getenv("APP_ENV", "local"),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", "4000")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        database_url=os.getenv("DATABASE_URL", DatabaseSettings().database_url),
        database_echo=os.getenv("DATABASE_ECHO", "false").lower()
        in {"1", "true", "yes", "on"},
        allowed_frontend_origins=os.getenv(
            "ALLOWED_FRONTEND_ORIGINS", "http://localhost:3000"
        ),
        auth_provider=os.getenv("AUTH_PROVIDER", "oidc"),
        auth_issuer_url=os.getenv("AUTH_ISSUER_URL") or None,
        auth_audience=os.getenv("AUTH_AUDIENCE") or None,
        auth_jwt_algorithms=os.getenv("AUTH_JWT_ALGORITHMS", "HS256"),
        auth_token_secret=os.getenv("AUTH_TOKEN_SECRET") or None,
    )
