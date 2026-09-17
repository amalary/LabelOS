"""Google workload authentication, deliberately independent of human/WorkOS auth."""

import asyncio
import os
import re
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
import jwt
from fastapi import HTTPException, Request

from labelos_api.config import Settings
from labelos_api.services.scheduling_processor import SchedulingWorker

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
AUTH_TIMEOUT_SECONDS = 5


def validate_worker_settings(settings: Settings, *, local_cli: bool = False) -> None:
    """Worker-only startup validation; no WorkOS or provider secrets are needed."""
    settings.validate_delivery_receiver()
    if not settings.database_url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("Scheduling workers require PostgreSQL with asyncpg")
    if settings.database_echo:
        raise RuntimeError("Worker DATABASE_ECHO must be false")
    if settings.scheduling_worker_workspace_id is None:
        raise RuntimeError("SCHEDULING_WORKER_WORKSPACE_ID is required")
    if (
        settings.scheduling_worker_lease_seconds
        <= settings.scheduling_worker_timeout_seconds
    ):
        raise RuntimeError("Worker lease must exceed the sweep timeout")
    if local_cli:
        if (
            settings.scheduling_worker_auth_mode != "local-cli"
            or not settings.is_development
            or os.getenv("K_SERVICE")
            or os.getenv("CLOUD_RUN_JOB")
            or urlsplit(settings.database_url).hostname
            not in {"localhost", "127.0.0.1", "::1"}
            or urlsplit(settings.database_url).query
        ):
            raise RuntimeError("Local execution requires local-cli and a loopback DB")
        return
    if settings.scheduling_worker_auth_mode != "google-oidc":
        raise RuntimeError("HTTP workers require google-oidc authentication")
    if (os.getenv("K_SERVICE") or os.getenv("CLOUD_RUN_JOB")) and (
        not settings.requires_strict_startup_validation
    ):
        raise RuntimeError("Cloud Run workers require a production-like APP_ENV")
    if not re.fullmatch(
        r"[a-z][a-z0-9-]*@[a-z0-9-]+\.iam\.gserviceaccount\.com",
        settings.scheduling_worker_service_account_email or "",
    ):
        raise RuntimeError("A dedicated worker service account email is required")
    if not re.fullmatch(
        r"[0-9]{1,32}", settings.scheduling_worker_service_account_subject or ""
    ):
        raise RuntimeError("Worker service account numeric unique ID is required")
    audience = urlsplit(settings.scheduling_worker_oidc_audience or "")
    if (
        audience.scheme != "https"
        or not audience.hostname
        or not audience.hostname.endswith(".run.app")
        or audience.username
        or audience.password
        or audience.port
        or audience.path
        or audience.query
        or audience.fragment
    ):
        raise RuntimeError("Worker OIDC audience must be the Cloud Run service origin")


async def _google_signing_key(token: str):
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
        raise jwt.InvalidTokenError()
    # Fixed HTTPS trust root. Never follow token-supplied jku/x5u/issuer URLs.
    async with httpx.AsyncClient(timeout=AUTH_TIMEOUT_SECONDS) as client:
        response = await client.get(GOOGLE_JWKS_URL)
        response.raise_for_status()
        keys = jwt.PyJWKSet.from_dict(response.json())
    key = keys[header["kid"]]
    if key.key_type != "RSA" or key.algorithm_name != "RS256":
        raise jwt.InvalidTokenError()
    return key.key


async def authenticate_worker(request: Request, settings: Settings) -> SchedulingWorker:
    headers = request.headers.getlist("authorization")
    if len(headers) != 1 or len(headers[0]) > 16384:
        raise HTTPException(401, "worker_authentication_required")
    parts = headers[0].split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(401, "worker_authentication_required")
    try:
        async with asyncio.timeout(AUTH_TIMEOUT_SECONDS):
            key = await _google_signing_key(parts[1])
        claims = jwt.decode(
            parts[1],
            key,
            algorithms=["RS256"],
            audience=settings.scheduling_worker_oidc_audience,
            issuer=GOOGLE_ISSUERS,
            options={
                "require": [
                    "iss",
                    "aud",
                    "sub",
                    "exp",
                    "iat",
                    "email",
                    "email_verified",
                ],
                "strict_aud": True,
            },
        )
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise HTTPException(401, "invalid_worker_token") from None
    except (httpx.HTTPError, TimeoutError):
        raise HTTPException(503, "worker_authentication_unavailable") from None
    if (
        claims["sub"] != settings.scheduling_worker_service_account_subject
        or claims["email"] != settings.scheduling_worker_service_account_email
        or claims["email_verified"] is not True
    ):
        raise HTTPException(403, "worker_identity_denied")
    assert settings.scheduling_worker_workspace_id is not None
    return SchedulingWorker(
        principal_id=uuid5(NAMESPACE_URL, f"google-service-account:{claims['sub']}"),
        instance_id=uuid4(),
        workspace_ids=frozenset({settings.scheduling_worker_workspace_id}),
    )
