from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from labelos_api.config import Settings

WORKOS_JWT_ALGORITHM = "RS256"
REQUIRED_WORKOS_CLAIMS = ("exp", "iss", "sub", "sid")
JWKS_CACHE_LIFESPAN_SECONDS = 300


class WorkOSJWTError(Exception):
    pass


@dataclass(frozen=True)
class WorkOSAuthenticatedUser:
    workos_user_id: str
    session_id: str
    organization_id: str | None = None
    role: str | None = None
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    email: str | None = None
    display_name: str | None = None


def _normalize_issuer(issuer: str) -> str:
    return issuer.rstrip("/")


def _accepted_issuers(issuer: str) -> tuple[str, str]:
    normalized = _normalize_issuer(issuer)
    return (normalized, f"{normalized}/")


def _string_tuple_claim(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(item for item in value if isinstance(item, str))
    return ()


@lru_cache(maxsize=16)
def _cached_jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(
        jwks_url,
        cache_jwk_set=True,
        lifespan=JWKS_CACHE_LIFESPAN_SECONDS,
    )


def _decode_options(settings: Settings) -> dict[str, object]:
    options: dict[str, object] = {"require": list(REQUIRED_WORKOS_CLAIMS)}
    if settings.workos_audience is None:
        options["verify_aud"] = False
    return options


def _decode_token(token: str, settings: Settings) -> dict[str, object]:
    if not settings.workos_client_id:
        raise WorkOSJWTError("WORKOS_CLIENT_ID is required for WorkOS JWT validation")

    try:
        signing_key = _cached_jwks_client(
            settings.resolved_workos_jwks_url
        ).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=[WORKOS_JWT_ALGORITHM],
            audience=settings.workos_audience,
            issuer=_accepted_issuers(settings.workos_issuer_url),
            options=_decode_options(settings),
        )
    except (PyJWTError, ValueError) as exc:
        raise WorkOSJWTError("Token is invalid") from exc


def validate_workos_jwt(token: str, settings: Settings) -> WorkOSAuthenticatedUser:
    claims = _decode_token(token, settings)

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise WorkOSJWTError("Token subject is missing")

    session_id = claims.get("sid")
    if not isinstance(session_id, str) or not session_id:
        raise WorkOSJWTError("Token session is missing")

    email = claims.get("email")
    display_name = claims.get("name")
    organization_id = claims.get("org_id")
    role = claims.get("role")
    roles = _string_tuple_claim(claims.get("roles"))
    if isinstance(role, str):
        roles = (role, *tuple(item for item in roles if item != role))
    return WorkOSAuthenticatedUser(
        workos_user_id=subject,
        session_id=session_id,
        organization_id=organization_id if isinstance(organization_id, str) else None,
        role=role if isinstance(role, str) else None,
        roles=roles,
        permissions=_string_tuple_claim(claims.get("permissions")),
        email=email if isinstance(email, str) else None,
        display_name=display_name if isinstance(display_name, str) else None,
    )
