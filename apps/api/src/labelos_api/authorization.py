from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, status
from labelos_database.models import MembershipRole

from labelos_api.auth import (
    AuthenticatedPrincipal,
    CurrentUserContext,
    get_current_principal,
    get_current_user_context,
    has_role_at_least,
)


class Permission(StrEnum):
    organization_manage = "organization:manage"
    members_manage = "members:manage"
    artists_view = "artists:view"
    artists_manage = "artists:manage"
    releases_view = "releases:view"
    releases_manage = "releases:manage"
    campaigns_view = "campaigns:view"
    campaigns_manage = "campaigns:manage"
    analytics_view = "analytics:view"
    royalties_view = "royalties:view"
    royalties_manage = "royalties:manage"
    contracts_view = "contracts:view"
    contracts_manage = "contracts:manage"
    agents_view = "agents:view"
    agents_manage = "agents:manage"
    settings_manage = "settings:manage"


APP_ROLES: tuple[MembershipRole, ...] = (
    MembershipRole.owner,
    MembershipRole.admin,
    MembershipRole.member,
)

INITIAL_ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.owner: frozenset(Permission),
    MembershipRole.admin: frozenset(
        {
            Permission.members_manage,
            Permission.artists_view,
            Permission.artists_manage,
            Permission.releases_view,
            Permission.releases_manage,
            Permission.campaigns_view,
            Permission.campaigns_manage,
            Permission.analytics_view,
            Permission.contracts_view,
            Permission.contracts_manage,
            Permission.agents_view,
            Permission.agents_manage,
            Permission.settings_manage,
        }
    ),
    MembershipRole.member: frozenset(
        {
            Permission.artists_view,
            Permission.releases_view,
            Permission.campaigns_view,
            Permission.analytics_view,
            Permission.royalties_view,
            Permission.contracts_view,
            Permission.agents_view,
        }
    ),
}


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _principal_roles(principal: AuthenticatedPrincipal) -> tuple[MembershipRole, ...]:
    return tuple(role for role in principal.membership_roles if role in APP_ROLES)


def require_authenticated_user() -> Callable[..., AuthenticatedPrincipal]:
    return get_current_principal


def require_organization() -> Callable[..., CurrentUserContext]:
    async def dependency(
        context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    ) -> CurrentUserContext:
        if context.principal.organization_id is None:
            raise _forbidden("Organization context required")
        return context

    return dependency


def require_role(
    required_role: MembershipRole | str,
) -> Callable[..., CurrentUserContext]:
    required = (
        required_role
        if isinstance(required_role, MembershipRole)
        else MembershipRole(required_role)
    )

    async def dependency(
        context: Annotated[CurrentUserContext, Depends(require_organization())],
    ) -> CurrentUserContext:
        principal_roles = _principal_roles(context.principal)
        if any(has_role_at_least(actual, required) for actual in principal_roles):
            return context
        raise _forbidden("Insufficient role")

    return dependency


def require_permission(
    required_permission: Permission | str,
) -> Callable[..., CurrentUserContext]:
    required = (
        required_permission
        if isinstance(required_permission, Permission)
        else Permission(required_permission)
    )

    async def dependency(
        context: Annotated[CurrentUserContext, Depends(require_organization())],
    ) -> CurrentUserContext:
        if required.value in context.principal.permissions:
            return context
        raise _forbidden("Insufficient permission")

    return dependency
