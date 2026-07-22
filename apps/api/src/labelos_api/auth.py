from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError
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
    session_id: str
    email: str | None = None
    display_name: str | None = None
    organization_id: str | None = None
    role: str | None = None
    permissions: tuple[str, ...] = ()


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

WORKOS_ROLE_MAP: dict[str, MembershipRole] = {
    "owner": MembershipRole.owner,
    "admin": MembershipRole.admin,
    "member": MembershipRole.member,
    "viewer": MembershipRole.viewer,
}


def has_role_at_least(actual: MembershipRole, required: MembershipRole) -> bool:
    return ROLE_ORDER[actual] >= ROLE_ORDER[required]


def _normalize_issuer(issuer: str) -> str:
    return issuer.rstrip("/")


def _accepted_issuers(issuer: str) -> tuple[str, str]:
    normalized = _normalize_issuer(issuer)
    return (normalized, f"{normalized}/")


def _workos_role_to_membership_role(role: str | None) -> MembershipRole:
    if role is None:
        return MembershipRole.member
    return WORKOS_ROLE_MAP.get(role.lower(), MembershipRole.member)


def _slug_from_workos_organization_id(workos_organization_id: str) -> str:
    return workos_organization_id.lower().replace("_", "-")[:120]


def _string_tuple_claim(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def principal_from_token(token: str, settings: Settings) -> AuthenticatedPrincipal:
    if not settings.workos_client_id:
        raise AuthTokenError("WORKOS_CLIENT_ID is required for WorkOS JWT validation")

    try:
        signing_key = PyJWKClient(
            settings.resolved_workos_jwks_url
        ).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.workos_client_id,
            issuer=_accepted_issuers(settings.workos_issuer_url),
        )
    except (PyJWTError, ValueError) as exc:
        raise AuthTokenError("Token is invalid") from exc

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise AuthTokenError("Token subject is missing")

    session_id = claims.get("sid")
    if not isinstance(session_id, str) or not session_id:
        raise AuthTokenError("Token session is missing")

    email = claims.get("email")
    name = claims.get("name")
    organization_id = claims.get("org_id")
    role = claims.get("role")
    return AuthenticatedPrincipal(
        provider=settings.auth_provider,
        subject=subject,
        session_id=session_id,
        email=email if isinstance(email, str) else None,
        display_name=name if isinstance(name, str) else None,
        organization_id=organization_id if isinstance(organization_id, str) else None,
        role=role if isinstance(role, str) else None,
        permissions=_string_tuple_claim(claims.get("permissions")),
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

    if principal.organization_id is not None:
        organization = await session.scalar(
            select(Organization).where(
                Organization.workos_organization_id == principal.organization_id
            )
        )
        if organization is None:
            organization = Organization(
                name=principal.organization_id,
                slug=_slug_from_workos_organization_id(principal.organization_id),
                workos_organization_id=principal.organization_id,
                owner_user_id=user.id,
            )
            session.add(organization)
            await session.flush()

        membership = await session.scalar(
            select(OrganizationMembership)
            .where(OrganizationMembership.organization_id == organization.id)
            .where(OrganizationMembership.user_id == user.id)
        )
        membership_role = _workos_role_to_membership_role(principal.role)
        if membership is None:
            session.add(
                OrganizationMembership(
                    organization_id=organization.id,
                    user_id=user.id,
                    role=membership_role,
                )
            )
            await session.commit()
        elif membership.role != membership_role:
            membership.role = membership_role
            await session.commit()

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


def require_permission(permission: str, context: CurrentUserContext) -> None:
    if permission in context.principal.permissions:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permission",
    )
