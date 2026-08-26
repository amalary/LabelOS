from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from labelos_database.models import MembershipRole, WorkspacePermission

from labelos_api.auth import (
    AuthenticatedPrincipal,
    CurrentUserContext,
    MembershipContext,
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


class Capability(StrEnum):
    artist_view = "artist.view"
    artist_edit = "artist.edit"
    artist_create = "artist.create"
    campaign_view = "campaign.view"
    campaign_create = "campaign.create"
    campaign_approve = "campaign.approve"
    release_view = "release.view"
    release_edit = "release.edit"
    contract_view = "contract.view"
    contract_upload = "contract.upload"
    contract_approve = "contract.approve"
    contract_sign_request = "contract.sign_request"
    royalty_view = "royalty.view"
    finance_view = "finance.view"
    analytics_view = "analytics.view"
    member_invite = "member.invite"
    member_remove = "member.remove"
    role_assign = "role.assign"
    workspace_manage = "workspace.manage"
    profile_edit = "profile.edit"


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

OWNER_CAPABILITIES = frozenset(Capability)
INITIAL_ROLE_CAPABILITIES: dict[MembershipRole, frozenset[Capability]] = {
    MembershipRole.owner: OWNER_CAPABILITIES,
    MembershipRole.admin: frozenset(
        {
            Capability.artist_view,
            Capability.artist_edit,
            Capability.artist_create,
            Capability.campaign_view,
            Capability.campaign_create,
            Capability.campaign_approve,
            Capability.release_view,
            Capability.release_edit,
            Capability.contract_view,
            Capability.contract_upload,
            Capability.contract_approve,
            Capability.contract_sign_request,
            Capability.royalty_view,
            Capability.finance_view,
            Capability.analytics_view,
            Capability.member_invite,
            Capability.member_remove,
            Capability.role_assign,
            Capability.workspace_manage,
            Capability.profile_edit,
        }
    ),
    MembershipRole.member: frozenset(
        {
            Capability.artist_view,
            Capability.campaign_view,
            Capability.release_view,
            Capability.analytics_view,
            Capability.profile_edit,
        }
    ),
}

CAPABILITY_DEPARTMENTS: dict[Capability, frozenset[str]] = {
    Capability.artist_view: frozenset({"artist", "a&r", "management"}),
    Capability.artist_edit: frozenset({"artist", "a&r", "management"}),
    Capability.artist_create: frozenset({"a&r", "management"}),
    Capability.campaign_view: frozenset({"marketing", "management"}),
    Capability.campaign_create: frozenset({"marketing", "management"}),
    Capability.campaign_approve: frozenset({"marketing", "management"}),
    Capability.release_view: frozenset({"release_operations", "management"}),
    Capability.release_edit: frozenset({"release_operations", "management"}),
    Capability.contract_view: frozenset({"legal", "contracts"}),
    Capability.contract_upload: frozenset({"legal", "contracts"}),
    Capability.contract_approve: frozenset({"legal", "contracts"}),
    Capability.contract_sign_request: frozenset({"legal", "contracts"}),
    Capability.royalty_view: frozenset({"finance", "royalties"}),
    Capability.finance_view: frozenset({"finance"}),
    Capability.analytics_view: frozenset({"analytics", "management"}),
    Capability.member_invite: frozenset({"administration"}),
    Capability.member_remove: frozenset({"administration"}),
    Capability.role_assign: frozenset({"administration"}),
    Capability.workspace_manage: frozenset({"administration"}),
    Capability.profile_edit: frozenset(),
}


@dataclass(frozen=True)
class AuthorizationResource:
    department: str | None = None


AuthorizationAction = Capability | Permission | MembershipRole | str
ResolvedAuthorizationAction = Capability | Permission | MembershipRole | None
AuthorizationWorkspace = MembershipContext | UUID | None


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _principal_roles(principal: AuthenticatedPrincipal) -> tuple[MembershipRole, ...]:
    return tuple(role for role in principal.membership_roles if role in APP_ROLES)


def _workspace_role(workspace_permission: WorkspacePermission) -> MembershipRole:
    return MembershipRole(workspace_permission.value)


def _valid_capabilities(
    capability_permissions: tuple[str, ...],
) -> frozenset[Capability]:
    return frozenset(
        Capability(capability)
        for capability in capability_permissions
        if capability in Capability._value2member_map_
    )


class AuthorizationService:
    def can(
        self,
        user: CurrentUserContext,
        workspace: AuthorizationWorkspace,
        capability: AuthorizationAction,
        resource: AuthorizationResource | dict[str, Any] | None = None,
    ) -> bool:
        action = self._normalize_action(capability)
        if action is None:
            return False
        if isinstance(action, Permission):
            return self.can_permission(user, action)
        if isinstance(action, MembershipRole):
            return self.can_role(user, action)
        return self.can_capability(
            user,
            action,
            workspace=workspace,
            resource=resource,
        )

    def can_role(
        self,
        user: CurrentUserContext,
        required_role: MembershipRole | str,
    ) -> bool:
        required = self._normalize_role(required_role)
        if required is None:
            return False
        principal_roles = _principal_roles(user.principal)
        return any(has_role_at_least(actual, required) for actual in principal_roles)

    def can_permission(
        self,
        user: CurrentUserContext,
        permission: Permission | str,
    ) -> bool:
        required = self._normalize_permission(permission)
        if required is None:
            return False
        return required.value in user.principal.permissions

    def can_access_department(
        self,
        user: CurrentUserContext,
        department_slug: str,
        *,
        workspace: AuthorizationWorkspace = None,
    ) -> bool:
        membership = self._resolve_workspace_membership(user, workspace)
        if membership is None:
            return False
        if membership.workspace_permission == WorkspacePermission.owner:
            return True
        return department_slug in membership.department_access

    def can_capability(
        self,
        user: CurrentUserContext,
        capability: Capability | str,
        *,
        workspace: AuthorizationWorkspace = None,
        resource: AuthorizationResource | dict[str, Any] | None = None,
    ) -> bool:
        required = self._normalize_capability(capability)
        if required is None:
            return False
        membership = self._resolve_workspace_membership(user, workspace)
        if membership is None:
            return False
        if membership.workspace_permission == WorkspacePermission.owner:
            return True
        department = self._resource_department(resource)
        allowed_departments = (
            frozenset({department})
            if department is not None
            else CAPABILITY_DEPARTMENTS.get(required, frozenset())
        )
        if allowed_departments and not any(
            self.can_access_department(user, slug, workspace=membership)
            for slug in allowed_departments
        ):
            return False
        return required in self.effective_capabilities(user, workspace=membership)

    def effective_capabilities(
        self,
        user: CurrentUserContext,
        *,
        workspace: AuthorizationWorkspace = None,
    ) -> frozenset[Capability]:
        membership = self._resolve_workspace_membership(user, workspace)
        if membership is None:
            return frozenset()
        workspace_role = _workspace_role(membership.workspace_permission)
        role_capabilities = INITIAL_ROLE_CAPABILITIES.get(workspace_role, frozenset())
        return frozenset(
            (
                *role_capabilities,
                *_valid_capabilities(membership.capability_permissions),
                *_valid_capabilities(membership.role_capabilities),
            )
        )

    def _resolve_workspace_membership(
        self,
        user: CurrentUserContext,
        workspace: AuthorizationWorkspace,
    ) -> MembershipContext | None:
        if isinstance(workspace, MembershipContext):
            return workspace if workspace.status == "active" else None
        if isinstance(workspace, UUID):
            for membership in user.memberships:
                if (
                    membership.workspace_id == workspace
                    and membership.status == "active"
                ):
                    return membership
            return None
        return user.active_membership

    def _resource_department(
        self,
        resource: AuthorizationResource | dict[str, Any] | None,
    ) -> str | None:
        if resource is None:
            return None
        if isinstance(resource, AuthorizationResource):
            return resource.department
        department = resource.get("department")
        return department if isinstance(department, str) else None

    def _normalize_action(
        self,
        action: AuthorizationAction,
    ) -> ResolvedAuthorizationAction:
        if isinstance(action, Capability | Permission | MembershipRole):
            return action
        capability = self._normalize_capability(action)
        if capability is not None:
            return capability
        permission = self._normalize_permission(action)
        if permission is not None:
            return permission
        role = self._normalize_role(action)
        if role is not None:
            return role
        return None

    def _normalize_capability(self, capability: Capability | str) -> Capability | None:
        if isinstance(capability, Capability):
            return capability
        if capability in Capability._value2member_map_:
            return Capability(capability)
        return None

    def _normalize_permission(self, permission: Permission | str) -> Permission | None:
        if isinstance(permission, Permission):
            return permission
        if permission in Permission._value2member_map_:
            return Permission(permission)
        return None

    def _normalize_role(self, role: MembershipRole | str) -> MembershipRole | None:
        if isinstance(role, MembershipRole):
            return role
        if role in MembershipRole._value2member_map_:
            return MembershipRole(role)
        return None


authorization_service = AuthorizationService()


def effective_capabilities(context: CurrentUserContext) -> frozenset[Capability]:
    return authorization_service.effective_capabilities(context)


def has_department_access(context: CurrentUserContext, department_slug: str) -> bool:
    return authorization_service.can_access_department(context, department_slug)


def has_capability(context: CurrentUserContext, capability: Capability | str) -> bool:
    return authorization_service.can_capability(context, capability)


def require_authenticated_user() -> Callable[..., AuthenticatedPrincipal]:
    return get_current_principal


def require_organization() -> Callable[..., CurrentUserContext]:
    async def dependency(
        context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    ) -> CurrentUserContext:
        if context.active_organization_id is None:
            raise _forbidden("Organization context required")
        return context

    return dependency


def require_workspace() -> Callable[..., CurrentUserContext]:
    async def dependency(
        context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    ) -> CurrentUserContext:
        if context.active_workspace_id is None:
            raise _forbidden("Workspace context required")
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
        if authorization_service.can(context, None, required):
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
        if authorization_service.can(context, None, required):
            return context
        raise _forbidden("Insufficient permission")

    return dependency


def require_capability(
    required_capability: Capability | str,
    *,
    department: str | None = None,
) -> Callable[..., CurrentUserContext]:
    required = (
        required_capability
        if isinstance(required_capability, Capability)
        else Capability(required_capability)
    )

    async def dependency(
        context: Annotated[CurrentUserContext, Depends(require_workspace())],
    ) -> CurrentUserContext:
        membership = context.active_membership
        if membership is None:
            raise _forbidden("Workspace context required")
        allowed_departments = (
            frozenset({department})
            if department is not None
            else CAPABILITY_DEPARTMENTS.get(required, frozenset())
        )
        if allowed_departments and not any(
            authorization_service.can_access_department(context, slug)
            for slug in allowed_departments
        ):
            raise _forbidden("Insufficient department access")
        if not authorization_service.can(
            context,
            membership,
            required,
            AuthorizationResource(department=department),
        ):
            raise _forbidden("Insufficient capability permission")
        return context

    return dependency
