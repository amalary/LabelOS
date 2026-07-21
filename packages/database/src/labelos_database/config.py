from pydantic import BaseModel, Field, PostgresDsn, field_validator


class DatabaseSettings(BaseModel):
    database_url: str = Field(
        default="postgresql+asyncpg://labelos:labelos_local_password@localhost:5432/labelos"
    )
    database_echo: bool = False

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_postgres_scheme(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if value.startswith("sqlite+aiosqlite://"):
            return value
        PostgresDsn(value)
        return value
