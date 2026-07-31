import json
import logging
import uuid

from fastapi.testclient import TestClient

from labelos_agents.logging import (
    JsonFormatter,
    configure_logging,
    correlation_headers,
    get_request_id,
)
from labelos_agents.main import create_app


def test_json_formatter_emits_cloud_logging_fields() -> None:
    formatter = JsonFormatter(
        service_name="labelos-agents",
        service_version="1.2.3",
        environment="test",
    )
    record = logging.makeLogRecord(
        {
            "name": "labelos_agents.test",
            "levelno": logging.ERROR,
            "levelname": "ERROR",
            "msg": "agent execution failed",
            "args": (),
            "authorization": "Bearer secret-token",
            "metadata": {"api_key": "secret-api-key", "safe": "value"},
        }
    )

    payload = json.loads(formatter.format(record))

    assert payload["severity"] == "ERROR"
    assert payload["message"] == "agent execution failed"
    assert payload["service"] == "labelos-agents"
    assert payload["environment"] == "test"
    assert payload["version"] == "1.2.3"
    assert payload["serviceContext"] == {
        "service": "labelos-agents",
        "version": "1.2.3",
    }
    assert payload["authorization"] == "[REDACTED]"
    assert payload["metadata"] == {"api_key": "[REDACTED]", "safe": "value"}


def test_request_logging_adds_request_id_response_header(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "req-test-123"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-test-123"


def test_request_logging_generates_request_id_response_header(
    client: TestClient,
) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    uuid.UUID(response.headers["x-request-id"])


def test_request_logging_rejects_untrusted_request_id_header(
    client: TestClient,
) -> None:
    untrusted_request_id = "x" * 129
    response = client.get("/health", headers={"X-Request-ID": untrusted_request_id})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != untrusted_request_id
    uuid.UUID(response.headers["x-request-id"])


def test_request_context_exposes_correlation_headers(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AGENTS_MODEL_PROVIDER", "mock")
    app = create_app()

    @app.get("/test/request-context")
    async def read_request_context() -> dict[str, object]:
        return {
            "request_id": get_request_id(),
            "correlation_headers": correlation_headers(),
        }

    with TestClient(app) as client:
        response = client.get(
            "/test/request-context",
            headers={
                "X-Request-ID": "req-context-123",
                "X-Cloud-Trace-Context": "105445aa7843bc8bf206b120001000/1;o=1",
                "traceparent": "00-105445aa7843bc8bf206b120001000-0000000000000001-01",
            },
        )

    assert response.json() == {
        "request_id": "req-context-123",
        "correlation_headers": {
            "x-request-id": "req-context-123",
            "x-cloud-trace-context": "105445aa7843bc8bf206b120001000/1;o=1",
            "traceparent": "00-105445aa7843bc8bf206b120001000-0000000000000001-01",
        },
    }
    assert get_request_id() is None


def test_request_logs_include_correlation_context(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AGENTS_MODEL_PROVIDER", "mock")
    monkeypatch.setenv("GCP_PROJECT_ID", "labelos-test")
    app = create_app()
    logger = logging.getLogger("labelos_agents.test")

    @app.get("/test/logging")
    async def log_inside_request() -> dict[str, str]:
        logger.info("inside correlation context")
        return {"status": "ok"}

    with TestClient(app) as client:
        response = client.get(
            "/test/logging",
            headers={
                "X-Request-ID": "req-log-123",
                "X-Cloud-Trace-Context": "105445aa7843bc8bf206b120001000/1;o=1",
            },
        )

    assert response.status_code == 200
    logs = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    payload = next(
        log for log in logs if log["message"] == "inside correlation context"
    )
    assert payload["request_id"] == "req-log-123"
    assert payload["logging.googleapis.com/insertId"] == "req-log-123"
    assert payload["trace_id"] == "105445aa7843bc8bf206b120001000"
    assert (
        payload["logging.googleapis.com/trace"]
        == "projects/labelos-test/traces/105445aa7843bc8bf206b120001000"
    )
    assert payload["logging.googleapis.com/spanId"] == "1"
    assert payload["logging.googleapis.com/trace_sampled"] is True


def test_production_logging_remains_json_when_text_is_requested() -> None:
    configure_logging("INFO", environment="production", log_format="text")

    root_logger = logging.getLogger()
    assert isinstance(root_logger.handlers[0].formatter, JsonFormatter)
