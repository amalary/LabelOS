import asyncio
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool, StaticPool
from sqlalchemy.schema import CreateSchema, DropSchema

from labelos_api.config import get_settings
from labelos_api.main import create_app


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ALLOWED_FRONTEND_ORIGINS", "http://localhost:3000")
    get_settings.cache_clear()
    return TestClient(create_app())


@pytest.fixture
def postgres_test_engine():
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_POSTGRES_URL to run PostgreSQL integration tests")
    schema = f"channel_test_{uuid4().hex}"
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "server_settings": {
                "search_path": schema,
                "timezone": "UTC",
                "lock_timeout": "10000",
                "statement_timeout": "20000",
            }
        },
    )

    async def create_schema():
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))

    async def cleanup():
        try:
            async with engine.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        finally:
            await engine.dispose()

    asyncio.run(create_schema())
    try:
        yield engine
    finally:
        asyncio.run(cleanup())


@pytest.fixture(
    params=["sqlite"] + (["postgresql"] if os.environ.get("TEST_POSTGRES_URL") else [])
)
def database_test_engine(request):
    """Run the same behavioral tests on PostgreSQL when configured (required in CI)."""
    if request.param == "postgresql":
        yield request.getfixturevalue("postgres_test_engine")
        return
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        yield engine
    finally:
        asyncio.run(engine.dispose())
