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
    auth_provider: str = "workos"
    workos_client_id: str | None = None
    workos_issuer_url: str = "https://api.workos.com"
    workos_jwks_url: str | None = None
    workos_audience: str | None = None
    workos_webhook_secret: str | None = None

    @field_validator("allowed_frontend_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in {"local", "development", "dev"}

    @property
    def is_test(self) -> bool:
        return self.environment.lower() == "test"

    @property
    def requires_strict_startup_validation(self) -> bool:
        return not self.is_development and not self.is_test

    @property
    def resolved_workos_jwks_url(self) -> str:
        if self.workos_jwks_url:
            return self.workos_jwks_url
        if not self.workos_client_id:
            raise ValueError("WORKOS_CLIENT_ID is required for WorkOS JWT validation")
        return f"https://api.workos.com/sso/jwks/{self.workos_client_id}"

    def validate_startup_environment(self) -> None:
        if (
            not self.requires_strict_startup_validation
            or self.auth_provider.lower() != "workos"
        ):
            return

        missing: list[str] = []
        if not self.workos_client_id:
            missing.append("WORKOS_CLIENT_ID")
        if not self.workos_issuer_url:
            missing.append("WORKOS_ISSUER_URL")
        if not self.workos_webhook_secret:
            missing.append("WORKOS_WEBHOOK_SECRET")

        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required WorkOS API environment: {joined}")

        _ = self.resolved_workos_jwks_url


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
        auth_provider=os.getenv("AUTH_PROVIDER", "workos"),
        workos_client_id=os.getenv("WORKOS_CLIENT_ID") or None,
        workos_issuer_url=os.getenv("WORKOS_ISSUER_URL", "https://api.workos.com"),
        workos_jwks_url=os.getenv("WORKOS_JWKS_URL") or None,
        workos_audience=os.getenv("WORKOS_AUDIENCE") or None,
        workos_webhook_secret=os.getenv("WORKOS_WEBHOOK_SECRET") or None,
    )
