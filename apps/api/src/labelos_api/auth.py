from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from labelos_database.models import (
    AuthIdentity,
    MembershipRole,
    Organization,
    OrganizationMembership,
    User,
)
from labelos_database.session import get_async_session
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_api.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)
SettingsDep = Annotated[Settings, Depends(get_settings)]
BearerCredentialsDep = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(bearer_scheme),
]


class AuthTokenError(Exception):
    pass


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    provider: str
    subject: str
    email: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class MembershipContext:
    organization_id: UUID
    organization_name: str
    organization_slug: str
    role: MembershipRole


@dataclass(frozen=True)
class CurrentUserContext:
    user: User
    principal: AuthenticatedPrincipal
    memberships: tuple[MembershipContext, ...]


ROLE_ORDER: dict[MembershipRole, int] = {
    MembershipRole.viewer: 0,
    MembershipRole.member: 1,
    MembershipRole.admin: 2,
    MembershipRole.owner: 3,
}


def has_role_at_least(actual: MembershipRole, required: MembershipRole) -> bool:
    return ROLE_ORDER[actual] >= ROLE_ORDER[required]


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _decode_json_segment(value: str) -> dict:
    try:
        decoded = json.loads(_b64url_decode(value))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthTokenError("Token is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise AuthTokenError("Token segment must be an object")
    return decoded


def _verify_hs256(token_head: str, signature: str, secret: str) -> None:
    expected = hmac.new(
        secret.encode("utf-8"),
        token_head.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    try:
        actual = _b64url_decode(signature)
    except ValueError as exc:
        raise AuthTokenError("Token signature is malformed") from exc
    if not hmac.compare_digest(expected, actual):
        raise AuthTokenError("Token signature is invalid")


def _validate_audience(claims: dict, expected_audience: str) -> None:
    token_audience = claims.get("aud")
    if isinstance(token_audience, str) and token_audience == expected_audience:
        return
    if isinstance(token_audience, Sequence) and expected_audience in token_audience:
        return
    raise AuthTokenError("Token audience is invalid")


def principal_from_token(token: str, settings: Settings) -> AuthenticatedPrincipal:
    token_parts = token.split(".")
    if len(token_parts) != 3:
        raise AuthTokenError("Token must be a compact JWT")

    encoded_header, encoded_claims, encoded_signature = token_parts
    header = _decode_json_segment(encoded_header)
    claims = _decode_json_segment(encoded_claims)
    algorithm = header.get("alg")

    if not isinstance(algorithm, str) or algorithm not in settings.auth_jwt_algorithms:
        raise AuthTokenError("Token algorithm is not allowed")

    if algorithm == "HS256":
        if not settings.auth_token_secret:
            raise AuthTokenError("AUTH_TOKEN_SECRET is required for HS256 validation")
        _verify_hs256(
            f"{encoded_header}.{encoded_claims}",
            encoded_signature,
            settings.auth_token_secret,
        )
    else:
        raise AuthTokenError("Configured token algorithm is not implemented locally")

    now = int(time.time())
    expires_at = claims.get("exp")
    if not isinstance(expires_at, int) or expires_at <= now:
        raise AuthTokenError("Token is expired")

    not_before = claims.get("nbf")
    if isinstance(not_before, int) and not_before > now:
        raise AuthTokenError("Token is not active yet")

    if settings.auth_issuer_url and claims.get("iss") != settings.auth_issuer_url:
        raise AuthTokenError("Token issuer is invalid")

    if settings.auth_audience:
        _validate_audience(claims, settings.auth_audience)

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise AuthTokenError("Token subject is missing")

    email = claims.get("email")
    name = claims.get("name")
    return AuthenticatedPrincipal(
        provider=settings.auth_provider,
        subject=subject,
        email=email if isinstance(email, str) else None,
        display_name=name if isinstance(name, str) else None,
    )


async def get_session(
    settings: SettingsDep,
):
    async for session in get_async_session(settings):
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_principal(
    credentials: BearerCredentialsDep,
    settings: SettingsDep,
) -> AuthenticatedPrincipal:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return principal_from_token(credentials.credentials, settings)
    except AuthTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def resolve_current_user(
    session: AsyncSession,
    principal: AuthenticatedPrincipal,
) -> CurrentUserContext:
    identity = await session.scalar(
        select(AuthIdentity)
        .options(selectinload(AuthIdentity.user))
        .where(AuthIdentity.provider == principal.provider)
        .where(AuthIdentity.subject == principal.subject)
    )
    if identity is None:
        if principal.email is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authenticated identity is missing an email claim",
            )
        user = await session.scalar(select(User).where(User.email == principal.email))
        if user is None:
            user = User(email=principal.email, display_name=principal.display_name)
            session.add(user)
            await session.flush()
        identity = AuthIdentity(
            user_id=user.id,
            provider=principal.provider,
            subject=principal.subject,
            email=principal.email,
        )
        session.add(identity)
        await session.commit()
        await session.refresh(user)
    else:
        user = identity.user

    rows = await session.execute(
        select(OrganizationMembership, Organization)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .where(OrganizationMembership.user_id == user.id)
    )
    memberships = tuple(
        MembershipContext(
            organization_id=organization.id,
            organization_name=organization.name,
            organization_slug=organization.slug,
            role=membership.role,
        )
        for membership, organization in rows.all()
    )
    return CurrentUserContext(user=user, principal=principal, memberships=memberships)


async def get_current_user_context(
    session: SessionDep,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> CurrentUserContext:
    return await resolve_current_user(session, principal)


def require_organization_role(
    organization_id: UUID,
    required_role: MembershipRole,
    context: CurrentUserContext,
) -> None:
    for membership in context.memberships:
        if membership.organization_id == organization_id and has_role_at_least(
            membership.role, required_role
        ):
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient organization role",
    )
