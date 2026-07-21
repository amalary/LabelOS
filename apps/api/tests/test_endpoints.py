from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


def test_root_endpoint(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Label OS API",
        "environment": "test",
        "version": "0.0.0",
    }


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_health_endpoint(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "labelos_api.routes.health.check_database_health",
        AsyncMock(return_value=True),
    )

    response = client.get("/health/database")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_status_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json() == {
        "service": "api",
        "status": "ok",
        "environment": "test",
        "version": "0.0.0",
    }


def test_unknown_route_returns_structured_error(client: TestClient) -> None:
    response = client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
