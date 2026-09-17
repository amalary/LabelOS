import asyncio
from uuid import uuid4

import pytest

from labelos_api.config import Settings, get_settings
from labelos_api.publishing_worker import run_sweep, validate_worker_settings


def test_disabled_worker_does_not_construct_database_or_provider():
    assert asyncio.run(run_sweep(Settings())) == {"status": "execution_disabled"}


@pytest.mark.parametrize(
    "values",
    [
        {"database_url": "sqlite+aiosqlite://"},
        {"database_echo": True},
        {"publishing_worker_workspace_id": None},
        {"environment": "production", "credential_store_backend": "memory"},
    ],
)
def test_worker_configuration_fails_closed(values):
    settings = Settings(
        **{
            "database_url": "postgresql+asyncpg://worker@localhost/test",
            "publishing_worker_workspace_id": uuid4(),
            **values,
        }
    )
    with pytest.raises(RuntimeError):
        validate_worker_settings(settings)


def test_publishing_settings_are_independent(monkeypatch):
    scope = uuid4()
    monkeypatch.setenv("PUBLISHING_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("PUBLISHING_WORKER_WORKSPACE_ID", str(scope))
    monkeypatch.setenv("SCHEDULING_EXECUTION_ENABLED", "false")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.publishing_execution_enabled
        assert not settings.scheduling_execution_enabled
        assert settings.publishing_worker_workspace_id == scope
    finally:
        get_settings.cache_clear()
