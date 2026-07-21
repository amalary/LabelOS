import pytest
from fastapi.testclient import TestClient

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
