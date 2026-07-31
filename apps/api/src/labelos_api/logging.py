import json
import logging
import os
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint

REQUEST_ID_HEADER = "x-request-id"
GCP_TRACE_HEADER = "x-cloud-trace-context"
TRACEPARENT_HEADER = "traceparent"

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:/@-]{1,128}$")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_trace_header: ContextVar[str | None] = ContextVar("trace_header", default=None)
_traceparent_header: ContextVar[str | None] = ContextVar(
    "traceparent_header", default=None
)

_RESERVED_LOG_RECORD_KEYS = set(logging.makeLogRecord({}).__dict__)
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "database_url",
)
_CLOUD_SEVERITY = {
    "CRITICAL": "CRITICAL",
    "ERROR": "ERROR",
    "WARNING": "WARNING",
    "INFO": "INFO",
    "DEBUG": "DEBUG",
    "NOTSET": "DEFAULT",
}


def _service_name(default: str = "labelos-api") -> str:
    return os.getenv("SERVICE_NAME") or default


def _project_id() -> str | None:
    return os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")


def _trace_fields(trace_header: str | None) -> dict[str, Any]:
    if not trace_header:
        return {}

    trace_span, trace_options = (trace_header.split(";", 1) + [""])[:2]
    trace_id, span_id = (trace_span.split("/", 1) + [""])[:2]
    if not trace_id:
        return {}

    payload: dict[str, Any] = {}
    payload["trace_id"] = trace_id
    project_id = _project_id()
    payload["logging.googleapis.com/trace"] = (
        f"projects/{project_id}/traces/{trace_id}" if project_id else trace_id
    )
    if span_id:
        payload["span_id"] = span_id
        payload["logging.googleapis.com/spanId"] = span_id
    if "o=1" in trace_options:
        payload["logging.googleapis.com/trace_sampled"] = True
    return payload


def _valid_request_id(value: str | None) -> str | None:
    if not value:
        return None
    request_id = value.strip()
    if _REQUEST_ID_PATTERN.fullmatch(request_id):
        return request_id
    return None


def get_request_id() -> str | None:
    return _request_id.get()


def correlation_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    request_id = _request_id.get()
    if request_id:
        headers[REQUEST_ID_HEADER] = request_id

    trace_header = _trace_header.get()
    if trace_header:
        headers[GCP_TRACE_HEADER] = trace_header

    traceparent = _traceparent_header.get()
    if traceparent:
        headers[TRACEPARENT_HEADER] = traceparent

    return headers


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, nested in value.items():
            key_text = str(key)
            if any(part in key_text.lower() for part in _SENSITIVE_KEY_PARTS):
                sanitized[key_text] = "[REDACTED]"
            else:
                sanitized[key_text] = _sanitize(nested)
        return sanitized
    if isinstance(value, list | tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and len(value) > 2048:
        return f"{value[:2048]}...[TRUNCATED]"
    return value


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _RESERVED_LOG_RECORD_KEYS or key.startswith("_"):
            continue
        fields[key] = _sanitize(value)
    return fields


class JsonFormatter(logging.Formatter):
    def __init__(self, *, service_name: str, service_version: str, environment: str):
        super().__init__()
        self.service_name = service_name
        self.service_version = service_version
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": _CLOUD_SEVERITY.get(record.levelname, record.levelname),
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
            "environment": self.environment,
            "version": self.service_version,
            "labels": {
                "service": self.service_name,
                "environment": self.environment,
            },
            "serviceContext": {
                "service": self.service_name,
                "version": self.service_version,
            },
        }

        request_id = _request_id.get()
        if request_id:
            payload["logging.googleapis.com/insertId"] = request_id
            payload["request_id"] = request_id

        payload.update(_trace_fields(_trace_header.get()))
        payload.update(_extra_fields(record))

        if record.exc_info:
            payload["stack_trace"] = self.formatException(record.exc_info)

        return json.dumps(_sanitize(payload), separators=(",", ":"))


def _allows_text_logs(environment: str) -> bool:
    return environment.lower() in {"local", "development", "dev", "test"}


def configure_logging(
    log_level: str,
    *,
    service_name: str | None = None,
    service_version: str = "0.0.0",
    environment: str = "local",
    log_format: str = "json",
) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if log_format.lower() == "text" and _allows_text_logs(environment):
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
    else:
        handler.setFormatter(
            JsonFormatter(
                service_name=service_name or _service_name(),
                service_version=service_version,
                environment=environment,
            )
        )
    root_logger.addHandler(handler)


async def request_logging_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    request_id = _valid_request_id(request.headers.get(REQUEST_ID_HEADER)) or str(
        uuid.uuid4()
    )
    request_id_token = _request_id.set(request_id)
    trace_token = _trace_header.set(request.headers.get(GCP_TRACE_HEADER))
    traceparent_token = _traceparent_header.set(request.headers.get(TRACEPARENT_HEADER))
    request.state.request_id = request_id
    request.state.correlation_headers = correlation_headers()
    logger = logging.getLogger("labelos_api.request")
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.exception(
            "Request failed",
            extra=_request_log_fields(request, 500, duration_ms),
        )
        raise
    else:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["x-request-id"] = request_id
        log_level = logging.WARNING if response.status_code >= 500 else logging.INFO
        logger.log(
            log_level,
            "Request completed",
            extra=_request_log_fields(request, response.status_code, duration_ms),
        )
        return response
    finally:
        _request_id.reset(request_id_token)
        _trace_header.reset(trace_token)
        _traceparent_header.reset(traceparent_token)


def _request_log_fields(
    request: Request, status_code: int, duration_ms: float
) -> dict[str, Any]:
    route = request.url.path
    return {
        "httpRequest": {
            "requestMethod": request.method,
            "requestUrl": str(request.url.replace(query=None)),
            "status": status_code,
            "latency": f"{duration_ms / 1000:.3f}s",
            "userAgent": request.headers.get("user-agent"),
            "remoteIp": request.client.host if request.client else None,
        },
        "route": route,
        "http_method": request.method,
        "http_status": status_code,
        "duration_ms": duration_ms,
    }
