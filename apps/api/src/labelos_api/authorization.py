from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import Depends, HTTPException, status
from labelos_database.capabilities import Capability
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


class ActorKind(StrEnum):
    user = "user"
    service_account = "service_account"
    ai_agent = "ai_agent"


class ResourceKind(StrEnum):
    workspace = "workspace"
    artist = "artist"
    release = "release"
    campaign = "campaign"
    contract = "contract"
    royalty = "royalty"
    analytics = "analytics"
    profile = "profile"


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
            Capability.workspace_view,
            Capability.workspace_update,
            Capability.workspace_member_view,
            Capability.workspace_member_invite,
            Capability.workspace_member_roles_manage,
            Capability.workspace_member_remove,
            Capability.role_view,
            Capability.role_create,
            Capability.role_update,
            Capability.role_delete,
            Capability.role_assign,
            Capability.artist_profile_view,
            Capability.artist_profile_edit,
            Capability.artist_profile_create,
            Capability.marketing_campaign_view,
            Capability.marketing_campaign_create,
            Capability.marketing_campaign_edit,
            Capability.marketing_campaign_approve,
            Capability.release_view,
            Capability.release_create,
            Capability.release_edit,
            Capability.release_approve,
            Capability.contract_view,
            Capability.contract_create,
            Capability.contract_edit,
            Capability.contract_review,
            Capability.contract_approve,
            Capability.contract_execute,
            Capability.royalty_view,
            Capability.royalty_statement_view,
            Capability.finance_view,
            Capability.finance_report_view,
            Capability.analytics_view,
            Capability.profile_view,
            Capability.profile_edit,
        }
    ),
    MembershipRole.member: frozenset(
        {
            Capability.artist_profile_view,
            Capability.marketing_campaign_view,
            Capability.release_view,
            Capability.analytics_view,
            Capability.profile_view,
            Capability.profile_edit,
        }
    ),
}

CAPABILITY_DEPARTMENTS: dict[Capability, frozenset[str]] = {
    Capability.workspace_view: frozenset({"administration", "management"}),
    Capability.workspace_update: frozenset({"administration"}),
    Capability.workspace_member_view: frozenset({"administration", "management"}),
    Capability.workspace_member_invite: frozenset({"administration"}),
    Capability.workspace_member_roles_manage: frozenset({"administration"}),
    Capability.workspace_member_remove: frozenset({"administration"}),
    Capability.role_view: frozenset({"administration", "management"}),
    Capability.role_create: frozenset({"administration"}),
    Capability.role_update: frozenset({"administration"}),
    Capability.role_delete: frozenset({"administration"}),
    Capability.role_assign: frozenset({"administration"}),
    Capability.profile_view: frozenset(),
    Capability.profile_edit: frozenset(),
    Capability.artist_profile_view: frozenset({"artist", "a&r", "management"}),
    Capability.artist_profile_edit: frozenset({"artist", "a&r", "management"}),
    Capability.artist_profile_create: frozenset({"a&r", "management"}),
    Capability.artist_profile_delete: frozenset({"a&r", "management"}),
    Capability.ar_scouting_view: frozenset({"a&r", "management"}),
    Capability.ar_scouting_create: frozenset({"a&r", "management"}),
    Capability.ar_evaluation_view: frozenset({"a&r", "management"}),
    Capability.ar_evaluation_create: frozenset({"a&r", "management"}),
    Capability.ar_signing_approve: frozenset({"a&r", "management"}),
    Capability.marketing_campaign_view: frozenset({"marketing", "management"}),
    Capability.marketing_campaign_create: frozenset({"marketing", "management"}),
    Capability.marketing_campaign_edit: frozenset({"marketing", "management"}),
    Capability.marketing_campaign_approve: frozenset({"marketing", "management"}),
    Capability.release_view: frozenset({"release_operations", "management"}),
    Capability.release_create: frozenset({"release_operations", "management"}),
    Capability.release_edit: frozenset({"release_operations", "management"}),
    Capability.release_approve: frozenset({"release_operations", "management"}),
    Capability.contract_view: frozenset({"legal", "contracts"}),
    Capability.contract_create: frozenset({"legal", "contracts"}),
    Capability.contract_edit: frozenset({"legal", "contracts"}),
    Capability.contract_review: frozenset({"legal", "contracts"}),
    Capability.contract_approve: frozenset({"legal", "contracts"}),
    Capability.contract_execute: frozenset({"legal", "contracts"}),
    Capability.royalty_view: frozenset({"finance", "royalties"}),
    Capability.royalty_calculate: frozenset({"finance", "royalties"}),
    Capability.royalty_statement_view: frozenset({"finance", "royalties"}),
    Capability.royalty_statement_create: frozenset({"finance", "royalties"}),
    Capability.finance_view: frozenset({"finance"}),
    Capability.finance_report_view: frozenset({"finance"}),
    Capability.finance_payment_view: frozenset({"finance"}),
    Capability.finance_payment_approve: frozenset({"finance"}),
    Capability.analytics_view: frozenset({"analytics", "management"}),
}


@dataclass(frozen=True)
class AuthorizationActor:
    """Actor metadata for authorization logs and future non-user principals."""

    kind: ActorKind
    subject: str
    user_id: UUID | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class AuthorizationResource:
    """Resource metadata used for workspace and future resource-aware decisions."""

    kind: ResourceKind | str | None = None
    id: UUID | str | None = None
    workspace_id: UUID | None = None
    department: str | None = None
    owner_actor: AuthorizationActor | None = None
    attributes: dict[str, Any] | None = None


@dataclass(frozen=True)
class AuthorizationDecision:
    actor: AuthorizationActor
    action: ResolvedAuthorizationAction
    workspace_id: UUID | None
    resource: AuthorizationResource | None
    allowed: bool
    reason: str


class WorkspaceAuthorizationContext(Protocol):
    principal: AuthenticatedPrincipal
    memberships: tuple[MembershipContext, ...]

    @property
    def active_membership(self) -> MembershipContext | None: ...


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


def actor_from_current_user(context: CurrentUserContext) -> AuthorizationActor:
    return AuthorizationActor(
        kind=ActorKind.user,
        subject=context.principal.subject,
        user_id=context.user.id,
        display_name=context.user.display_name,
    )


class AuthorizationService:
    def can(
        self,
        actor: WorkspaceAuthorizationContext,
        workspace: AuthorizationWorkspace,
        capability: AuthorizationAction,
        resource: AuthorizationResource | dict[str, Any] | None = None,
    ) -> bool:
        return self.decide(actor, workspace, capability, resource).allowed

    def decide(
        self,
        actor: WorkspaceAuthorizationContext,
        workspace: AuthorizationWorkspace,
        capability: AuthorizationAction,
        resource: AuthorizationResource | dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        action = self._normalize_action(capability)
        normalized_resource = self._normalize_resource(resource)
        actor_ref = self._actor_ref(actor)
        workspace_id = self._workspace_id(actor, workspace)
        if action is None:
            return AuthorizationDecision(
                actor=actor_ref,
                action=None,
                workspace_id=workspace_id,
                resource=normalized_resource,
                allowed=False,
                reason="unknown_action",
            )
        if isinstance(action, Permission):
            allowed = self.can_permission(actor, action)
            return AuthorizationDecision(
                actor=actor_ref,
                action=action,
                workspace_id=workspace_id,
                resource=normalized_resource,
                allowed=allowed,
                reason="permission_allowed" if allowed else "missing_permission",
            )
        if isinstance(action, MembershipRole):
            allowed = self.can_role(actor, action)
            return AuthorizationDecision(
                actor=actor_ref,
                action=action,
                workspace_id=workspace_id,
                resource=normalized_resource,
                allowed=allowed,
                reason="role_allowed" if allowed else "insufficient_role",
            )
        allowed = self.can_capability(
            actor,
            action,
            workspace=workspace,
            resource=normalized_resource,
        )
        return AuthorizationDecision(
            actor=actor_ref,
            action=action,
            workspace_id=workspace_id,
            resource=normalized_resource,
            allowed=allowed,
            reason="capability_allowed" if allowed else "missing_capability",
        )

    def can_role(
        self,
        actor: WorkspaceAuthorizationContext,
        required_role: MembershipRole | str,
    ) -> bool:
        required = self._normalize_role(required_role)
        if required is None:
            return False
        principal_roles = _principal_roles(actor.principal)
        return any(has_role_at_least(actual, required) for actual in principal_roles)

    def can_permission(
        self,
        actor: WorkspaceAuthorizationContext,
        permission: Permission | str,
    ) -> bool:
        required = self._normalize_permission(permission)
        if required is None:
            return False
        return required.value in actor.principal.permissions

    def can_access_department(
        self,
        actor: WorkspaceAuthorizationContext,
        department_slug: str,
        *,
        workspace: AuthorizationWorkspace = None,
    ) -> bool:
        membership = self._resolve_workspace_membership(actor, workspace)
        if membership is None:
            return False
        if membership.workspace_permission == WorkspacePermission.owner:
            return True
        return department_slug in membership.department_access

    def can_capability(
        self,
        actor: WorkspaceAuthorizationContext,
        capability: Capability | str,
        *,
        workspace: AuthorizationWorkspace = None,
        resource: AuthorizationResource | dict[str, Any] | None = None,
    ) -> bool:
        required = self._normalize_capability(capability)
        if required is None:
            return False
        membership = self._resolve_workspace_membership(actor, workspace)
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
            self.can_access_department(actor, slug, workspace=membership)
            for slug in allowed_departments
        ):
            return False
        return required in self.effective_capabilities(actor, workspace=membership)

    def effective_capabilities(
        self,
        actor: WorkspaceAuthorizationContext,
        *,
        workspace: AuthorizationWorkspace = None,
    ) -> frozenset[Capability]:
        membership = self._resolve_workspace_membership(actor, workspace)
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
        actor: WorkspaceAuthorizationContext,
        workspace: AuthorizationWorkspace,
    ) -> MembershipContext | None:
        if isinstance(workspace, MembershipContext):
            return workspace if workspace.status == "active" else None
        if isinstance(workspace, UUID):
            for membership in actor.memberships:
                if (
                    membership.workspace_id == workspace
                    and membership.status == "active"
                ):
                    return membership
            return None
        return actor.active_membership

    def _resource_department(
        self,
        resource: AuthorizationResource | dict[str, Any] | None,
    ) -> str | None:
        normalized = self._normalize_resource(resource)
        if normalized is None:
            return None
        return normalized.department

    def _normalize_resource(
        self,
        resource: AuthorizationResource | dict[str, Any] | None,
    ) -> AuthorizationResource | None:
        if resource is None or isinstance(resource, AuthorizationResource):
            return resource
        department = resource.get("department")
        kind = resource.get("kind")
        resource_id = resource.get("id")
        workspace_id = resource.get("workspace_id")
        attributes = resource.get("attributes")
        return AuthorizationResource(
            kind=kind if isinstance(kind, str) else None,
            id=resource_id if isinstance(resource_id, UUID | str) else None,
            workspace_id=workspace_id if isinstance(workspace_id, UUID) else None,
            department=department if isinstance(department, str) else None,
            attributes=attributes if isinstance(attributes, dict) else None,
        )

    def _actor_ref(self, actor: WorkspaceAuthorizationContext) -> AuthorizationActor:
        actor_ref = getattr(actor, "authorization_actor", None)
        if isinstance(actor_ref, AuthorizationActor):
            return actor_ref
        if isinstance(actor, CurrentUserContext):
            return actor_from_current_user(actor)
        return AuthorizationActor(
            kind=ActorKind.user,
            subject=actor.principal.subject,
            display_name=actor.principal.display_name,
        )

    def _workspace_id(
        self,
        actor: WorkspaceAuthorizationContext,
        workspace: AuthorizationWorkspace,
    ) -> UUID | None:
        if isinstance(workspace, MembershipContext):
            return workspace.workspace_id
        if isinstance(workspace, UUID):
            return workspace
        active_membership = actor.active_membership
        return active_membership.workspace_id if active_membership is not None else None

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
