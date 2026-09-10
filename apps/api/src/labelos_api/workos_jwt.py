from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote, urlparse, urlunparse

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from labelos_api.config import Settings

WORKOS_JWT_ALGORITHM = "RS256"
REQUIRED_WORKOS_CLAIMS = ("exp", "iss", "sub")
JWKS_CACHE_LIFESPAN_SECONDS = 300
WORKOS_API_ISSUER_URL = "https://api.workos.com"


class WorkOSJWTError(Exception):
    def __init__(
        self,
        message: str,
        *,
        phase: str = "unknown",
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.diagnostics = diagnostics or {}


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


def _claim_contains(value: object, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, Sequence):
        return expected in (item for item in value if isinstance(item, str))
    return False


def _is_client_scoped_workos_issuer(token_issuer: object, issuer: str) -> bool:
    if not isinstance(token_issuer, str):
        return False

    normalized = _normalize_issuer(issuer)
    normalized_token_issuer = _normalize_issuer(token_issuer)
    return normalized_token_issuer.startswith(f"{normalized}/user_management/")


def _client_id_from_workos_issuer(token_issuer: object, issuer: str) -> str | None:
    if not isinstance(token_issuer, str):
        return None

    normalized = _normalize_issuer(issuer)
    normalized_token_issuer = _normalize_issuer(token_issuer)
    prefix = f"{normalized}/user_management/"
    if not normalized_token_issuer.startswith(prefix):
        return None

    client_id = normalized_token_issuer.removeprefix(prefix).split("/", 1)[0]
    if client_id.startswith("client_") and client_id.replace("_", "").isalnum():
        return client_id
    return None


def _is_accepted_token_context(claims: dict[str, object], settings: Settings) -> bool:
    token_issuer = claims.get("iss")
    if not isinstance(token_issuer, str):
        return False

    normalized = _normalize_issuer(settings.workos_issuer_url)
    normalized_workos_api = _normalize_issuer(WORKOS_API_ISSUER_URL)
    normalized_token_issuer = _normalize_issuer(token_issuer)
    if normalized_token_issuer in {normalized, normalized_workos_api}:
        if _claim_contains(claims.get("client_id"), settings.workos_client_id or ""):
            return True
        if _claim_contains(claims.get("aud"), settings.workos_client_id or ""):
            return True
        return claims.get("client_id") is None and claims.get("aud") is None

    if settings.workos_client_id is None:
        return False

    if _is_client_scoped_workos_issuer(token_issuer, settings.workos_issuer_url) and (
        _claim_contains(claims.get("client_id"), settings.workos_client_id)
        or _claim_contains(claims.get("aud"), settings.workos_client_id)
    ):
        return True

    return (
        normalized != normalized_workos_api
        and _is_client_scoped_workos_issuer(token_issuer, WORKOS_API_ISSUER_URL)
        and (
            _claim_contains(claims.get("client_id"), settings.workos_client_id)
            or _claim_contains(claims.get("aud"), settings.workos_client_id)
        )
    )


def _workos_jwks_url(client_id: str) -> str:
    return f"https://api.workos.com/sso/jwks/{quote(client_id, safe='')}"


def _oauth_jwks_url(issuer: str) -> str:
    parsed = urlparse(_normalize_issuer(issuer))
    return urlunparse(
        parsed._replace(path="/oauth2/jwks", params="", query="", fragment="")
    )


def _candidate_jwks_urls_for_token(token: str, settings: Settings) -> tuple[str, ...]:
    if settings.workos_jwks_url:
        return (settings.workos_jwks_url,)

    try:
        unverified_claims = jwt.decode(token, options={"verify_signature": False})
    except PyJWTError:
        return (settings.resolved_workos_jwks_url,)

    token_issuer = unverified_claims.get("iss")
    issuer_client_id = _client_id_from_workos_issuer(
        token_issuer, settings.workos_issuer_url
    )
    if issuer_client_id is None:
        issuer_client_id = _client_id_from_workos_issuer(
            token_issuer, WORKOS_API_ISSUER_URL
        )
    if not issuer_client_id and not settings.workos_client_id:
        raise WorkOSJWTError("WORKOS_CLIENT_ID is required for WorkOS JWT validation")

    urls: list[str] = []
    normalized_issuer = _normalize_issuer(settings.workos_issuer_url)
    if normalized_issuer != _normalize_issuer(WORKOS_API_ISSUER_URL):
        urls.append(_oauth_jwks_url(settings.workos_issuer_url))

    candidate_client_ids = (issuer_client_id, settings.workos_client_id)
    for client_id in candidate_client_ids:
        if not client_id:
            continue
        url = _workos_jwks_url(client_id)
        if url not in urls:
            urls.append(url)
    return tuple(urls)


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
    options: dict[str, object] = {
        "require": list(REQUIRED_WORKOS_CLAIMS),
        "verify_iss": False,
    }
    if settings.workos_audience is None:
        options["verify_aud"] = False
    return options


def _decode_token(token: str, settings: Settings) -> dict[str, object]:
    if not settings.workos_client_id:
        raise WorkOSJWTError(
            "WORKOS_CLIENT_ID is required for WorkOS JWT validation",
            phase="configuration",
        )

    last_error: Exception | None = None
    candidate_urls = _candidate_jwks_urls_for_token(token, settings)
    for jwks_url in candidate_urls:
        try:
            signing_key = _cached_jwks_client(jwks_url).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=[WORKOS_JWT_ALGORITHM],
                audience=settings.workos_audience,
                options=_decode_options(settings),
            )
            break
        except PyJWTError as exc:
            last_error = exc
    else:
        raise WorkOSJWTError(
            "Token is invalid",
            phase="jwks_or_signature",
        ) from last_error

    try:
        if not _is_accepted_token_context(claims, settings):
            raise ValueError("Token issuer is invalid")
        return claims
    except ValueError as exc:
        raise WorkOSJWTError(
            "Token is invalid",
            phase="issuer_or_client_context",
        ) from exc


def validate_workos_jwt(token: str, settings: Settings) -> WorkOSAuthenticatedUser:
    claims = _decode_token(token, settings)

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise WorkOSJWTError("Token subject is missing")

    session_id = claims.get("sid")
    email = claims.get("email")
    display_name = claims.get("name")
    organization_id = claims.get("org_id")
    role = claims.get("role")
    roles = _string_tuple_claim(claims.get("roles"))
    if isinstance(role, str):
        roles = (role, *tuple(item for item in roles if item != role))
    return WorkOSAuthenticatedUser(
        workos_user_id=subject,
        session_id=session_id if isinstance(session_id, str) else "",
        organization_id=organization_id if isinstance(organization_id, str) else None,
        role=role if isinstance(role, str) else None,
        roles=roles,
        permissions=_string_tuple_claim(claims.get("permissions")),
        email=email if isinstance(email, str) else None,
        display_name=display_name if isinstance(display_name, str) else None,
    )
