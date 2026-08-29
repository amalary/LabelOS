from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from inspect import isawaitable
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from labelos_database.capabilities import Capability
from labelos_database.models import (
    AnalyticsMetricDefinition,
    AnalyticsObservation,
    Artist,
    ArtistProfile,
    Campaign,
    MembershipDepartmentAccess,
    MembershipRole,
    Organization,
    OrganizationMembership,
    Role,
    RoleCapability,
    User,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspacePermission,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_api.auth import (
    AuthenticatedPrincipal,
    CurrentUserContext,
    MembershipContext,
    SessionDep,
    get_current_principal,
    get_current_user_context,
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
    workspace_membership = "workspace_membership"
    artist = "artist"
    artist_profile = "artist_profile"
    release = "release"
    campaign = "campaign"
    contract = "contract"
    royalty = "royalty"
    analytics = "analytics"
    analytics_metric_definition = "analytics_metric_definition"
    analytics_observation = "analytics_observation"
    profile = "profile"
    universal_profile = "universal_profile"


# TODO(remove after WorkOS permission claims are backfilled independently of
# role slugs): keep this compatibility map only for legacy session tests and
# bootstrap paths that still receive role-derived WorkOS permissions.
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
# TODO(remove after every active workspace membership has explicit role
# assignments and capability grants): this maps legacy workspace_permission rows
# into the capability system without letting route handlers authorize by role.
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
            Capability.analytics_create,
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
    Capability.analytics_create: frozenset({"analytics", "management"}),
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


@dataclass(frozen=True)
class LegacyWorkspaceAuthorizationMembership:
    workspace_permission: WorkspacePermission = WorkspacePermission.member
    capability_permissions: tuple[str, ...] = ()

    @property
    def approved_department_access(self) -> tuple[str, ...]:
        return ()


class WorkspaceAuthorizationContext(Protocol):
    principal: AuthenticatedPrincipal
    memberships: tuple[MembershipContext, ...]

    @property
    def active_membership(self) -> MembershipContext | None: ...


AuthorizationAction = Capability | Permission | str
ResolvedAuthorizationAction = Capability | Permission | None
AuthorizationWorkspace = MembershipContext | UUID | None
AuthorizationActorInput = (
    WorkspaceAuthorizationContext | CurrentUserContext | User | UUID
)
WorkspaceContextResolver = Callable[
    [Request, CurrentUserContext],
    AuthorizationWorkspace,
]
ResourceContextResolver = Callable[
    [Request, CurrentUserContext],
    AuthorizationResource | dict[str, Any] | None,
]


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _request_value(request: Request, name: str) -> str | None:
    value = request.path_params.get(name)
    if value is None:
        value = request.query_params.get(name)
    return str(value) if value is not None else None


def _request_uuid(request: Request, name: str) -> UUID | None:
    value = _request_value(request, name)
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


async def _resolve_dependency_value(
    resolver: Callable[..., Any],
    request: Request,
    context: CurrentUserContext,
) -> Any:
    try:
        value = resolver(request, context)
    except TypeError:
        value = resolver(request)
    if isawaitable(value):
        return await value
    return value


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
    async def has_capability(
        self,
        session: AsyncSession,
        actor: AuthorizationActorInput,
        workspace: AuthorizationWorkspace,
        capability: Capability | str,
        resource: AuthorizationResource | dict[str, Any] | None = None,
    ) -> bool:
        return (
            await self.decide_capability(
                session,
                actor=actor,
                workspace=workspace,
                capability=capability,
                resource=resource,
            )
        ).allowed

    async def require_capability(
        self,
        session: AsyncSession,
        actor: AuthorizationActorInput,
        workspace: AuthorizationWorkspace,
        capability: Capability | str,
        resource: AuthorizationResource | dict[str, Any] | None = None,
    ) -> None:
        if not await self.has_capability(
            session,
            actor=actor,
            workspace=workspace,
            capability=capability,
            resource=resource,
        ):
            raise _forbidden("Insufficient capability permission")

    async def decide_capability(
        self,
        session: AsyncSession,
        *,
        actor: AuthorizationActorInput,
        workspace: AuthorizationWorkspace,
        capability: Capability | str,
        resource: AuthorizationResource | dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        actor_ref = self._actor_ref_from_input(actor)
        workspace_id = self._workspace_id_from_input(actor, workspace)
        normalized_resource = self._normalize_resource(resource)
        required = self._normalize_capability(capability)
        if required is None:
            return AuthorizationDecision(
                actor=actor_ref,
                action=None,
                workspace_id=workspace_id,
                resource=normalized_resource,
                allowed=False,
                reason="unknown_capability",
            )
        if workspace_id is None:
            return AuthorizationDecision(
                actor=actor_ref,
                action=required,
                workspace_id=None,
                resource=normalized_resource,
                allowed=False,
                reason="invalid_workspace",
            )
        if not self._resource_scope_is_valid(resource, workspace_id):
            return AuthorizationDecision(
                actor=actor_ref,
                action=required,
                workspace_id=workspace_id,
                resource=normalized_resource,
                allowed=False,
                reason="invalid_resource_scope",
            )
        if not await self._resource_is_accessible_from_workspace(
            session,
            resource=normalized_resource,
            workspace_id=workspace_id,
        ):
            return AuthorizationDecision(
                actor=actor_ref,
                action=required,
                workspace_id=workspace_id,
                resource=normalized_resource,
                allowed=False,
                reason="invalid_resource_scope",
            )

        result = await self._load_authorization_state(
            session,
            actor=actor,
            workspace_id=workspace_id,
        )
        if result is None:
            return AuthorizationDecision(
                actor=actor_ref,
                action=required,
                workspace_id=workspace_id,
                resource=normalized_resource,
                allowed=False,
                reason="membership_not_found",
            )
        membership, workspace_membership = result
        if membership.workspace_permission == WorkspacePermission.owner:
            return AuthorizationDecision(
                actor=actor_ref,
                action=required,
                workspace_id=workspace_id,
                resource=normalized_resource,
                allowed=True,
                reason="workspace_owner",
            )

        effective = self._effective_capabilities_for_membership(
            membership,
            workspace_membership,
            workspace_id=workspace_id,
        )
        if effective is None:
            return AuthorizationDecision(
                actor=actor_ref,
                action=required,
                workspace_id=workspace_id,
                resource=normalized_resource,
                allowed=False,
                reason="invalid_role_mapping",
            )
        if not self._has_department_scope(
            membership,
            required,
            resource=normalized_resource,
        ):
            return AuthorizationDecision(
                actor=actor_ref,
                action=required,
                workspace_id=workspace_id,
                resource=normalized_resource,
                allowed=False,
                reason="insufficient_department_access",
            )

        allowed = required in effective
        reason = "capability_allowed" if allowed else "missing_capability"
        if allowed:
            allowed, reason = await self._resource_action_is_authorized(
                session,
                capability=required,
                membership=membership,
                workspace_membership=workspace_membership,
                resource=normalized_resource,
            )
        return AuthorizationDecision(
            actor=actor_ref,
            action=required,
            workspace_id=workspace_id,
            resource=normalized_resource,
            allowed=allowed,
            reason=reason,
        )

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
        # TODO(remove after owner memberships receive explicit all-department
        # access grants): owner remains a migration compatibility shortcut for
        # department scope, while actions themselves are checked as capabilities.
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
        workspace_id = self._workspace_id(actor, membership)
        if workspace_id is None or not self._resource_scope_is_valid(
            resource,
            workspace_id,
        ):
            return False
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

    async def _load_authorization_state(
        self,
        session: AsyncSession,
        *,
        actor: AuthorizationActorInput,
        workspace_id: UUID,
    ) -> (
        tuple[
            OrganizationMembership | LegacyWorkspaceAuthorizationMembership,
            WorkspaceMembership,
        ]
        | None
    ):
        actor_user_id = self._actor_user_id(actor)
        if actor_user_id is None:
            return None
        workspace_exists = await session.scalar(
            select(Organization.id).where(Organization.id == workspace_id)
        )
        if workspace_exists is None:
            return None
        membership = await session.scalar(
            select(OrganizationMembership)
            .options(
                selectinload(
                    OrganizationMembership.department_access_grants
                ).selectinload(MembershipDepartmentAccess.department),
                selectinload(OrganizationMembership.workspace_membership)
                .selectinload(WorkspaceMembership.role_assignments)
                .selectinload(WorkspaceMembershipRole.role)
                .selectinload(Role.capability_links)
                .selectinload(RoleCapability.capability),
            )
            .where(OrganizationMembership.organization_id == workspace_id)
            .where(OrganizationMembership.user_id == actor_user_id)
            .where(OrganizationMembership.status == "active")
        )
        if (
            membership is None
            or membership.workspace_membership is None
            or membership.workspace_membership.status != "active"
        ):
            legacy_workspace_membership = await session.scalar(
                select(WorkspaceMembership)
                .options(
                    selectinload(WorkspaceMembership.role_assignments)
                    .selectinload(WorkspaceMembershipRole.role)
                    .selectinload(Role.capability_links)
                    .selectinload(RoleCapability.capability),
                )
                .join(WorkspaceMembership.profile)
                .where(WorkspaceMembership.workspace_id == workspace_id)
                .where(WorkspaceMembership.status == "active")
                .where(WorkspaceMembership.organization_membership_id.is_(None))
                .where(WorkspaceMembership.profile.has(user_id=actor_user_id))
            )
            if legacy_workspace_membership is None:
                return None
            return (
                LegacyWorkspaceAuthorizationMembership(),
                legacy_workspace_membership,
            )
        return membership, membership.workspace_membership

    def _effective_capabilities_for_membership(
        self,
        membership: OrganizationMembership | LegacyWorkspaceAuthorizationMembership,
        workspace_membership: WorkspaceMembership,
        *,
        workspace_id: UUID,
    ) -> frozenset[Capability] | None:
        workspace_role = _workspace_role(membership.workspace_permission)
        capabilities = set(INITIAL_ROLE_CAPABILITIES.get(workspace_role, frozenset()))
        capabilities.update(
            _valid_capabilities(tuple(membership.capability_permissions))
        )
        for role in workspace_membership.roles:
            if role.workspace_id not in {None, workspace_id}:
                return None
            for db_capability in role.capabilities:
                normalized = self._normalize_capability(db_capability.key)
                if normalized is None:
                    return None
                capabilities.add(normalized)
        return frozenset(capabilities)

    def _has_department_scope(
        self,
        membership: OrganizationMembership,
        capability: Capability,
        *,
        resource: AuthorizationResource | None,
    ) -> bool:
        department = resource.department if resource is not None else None
        required_departments = (
            frozenset({department})
            if department is not None
            else CAPABILITY_DEPARTMENTS.get(capability, frozenset())
        )
        if not required_departments:
            return True
        department_access = set(membership.approved_department_access)
        return any(slug in department_access for slug in required_departments)

    def _actor_user_id(self, actor: AuthorizationActorInput) -> UUID | None:
        if isinstance(actor, UUID):
            return actor
        if isinstance(actor, User):
            return actor.id
        user = getattr(actor, "user", None)
        if isinstance(user, User):
            return user.id
        return None

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

    def _resource_scope_is_valid(
        self,
        resource: AuthorizationResource | dict[str, Any] | None,
        workspace_id: UUID,
    ) -> bool:
        if resource is None:
            return True
        if isinstance(resource, AuthorizationResource):
            if resource.workspace_id is not None and not isinstance(
                resource.workspace_id,
                UUID,
            ):
                return False
            if resource.department is not None and not isinstance(
                resource.department,
                str,
            ):
                return False
            if resource.kind is not None and not isinstance(resource.kind, str):
                return False
            if resource.id is not None and not isinstance(resource.id, UUID | str):
                return False
        if isinstance(resource, dict):
            if "workspace_id" in resource and not isinstance(
                resource.get("workspace_id"),
                UUID,
            ):
                return False
            if "department" in resource and not isinstance(
                resource.get("department"),
                str,
            ):
                return False
            if "kind" in resource and not isinstance(resource.get("kind"), str):
                return False
            if "id" in resource and not isinstance(resource.get("id"), UUID | str):
                return False
        normalized = self._normalize_resource(resource)
        if normalized is None or normalized.workspace_id is None:
            return True
        return normalized.workspace_id == workspace_id

    async def _resource_is_accessible_from_workspace(
        self,
        session: AsyncSession,
        *,
        resource: AuthorizationResource | None,
        workspace_id: UUID,
    ) -> bool:
        """Resolve known resources to the workspace before capability checks.

        This intentionally covers only first-party resource relationships that exist
        today. Future enterprise hierarchy or shared-resource rules can extend this
        resolver without changing callers.
        """

        if resource is None or resource.id is None or resource.kind is None:
            return True

        kind = str(resource.kind)
        resource_id = resource.id
        if not isinstance(resource_id, UUID):
            return False

        if kind == ResourceKind.workspace:
            return resource_id == workspace_id
        if kind == ResourceKind.analytics:
            return resource_id == workspace_id
        if kind in {ResourceKind.profile, ResourceKind.universal_profile}:
            return (
                await session.scalar(
                    select(WorkspaceMembership.id)
                    .where(WorkspaceMembership.workspace_id == workspace_id)
                    .where(WorkspaceMembership.profile_id == resource_id)
                    .where(WorkspaceMembership.status == "active")
                )
            ) is not None
        if kind == ResourceKind.workspace_membership:
            return (
                await session.scalar(
                    select(WorkspaceMembership.id)
                    .where(WorkspaceMembership.id == resource_id)
                    .where(WorkspaceMembership.workspace_id == workspace_id)
                    .where(WorkspaceMembership.status == "active")
                )
            ) is not None
        if kind == ResourceKind.artist:
            return (
                await session.scalar(
                    select(Artist.id)
                    .where(Artist.id == resource_id)
                    .where(Artist.organization_id == workspace_id)
                )
            ) is not None
        if kind == ResourceKind.artist_profile:
            return (
                await session.scalar(
                    select(ArtistProfile.id)
                    .join(ArtistProfile.artist)
                    .where(ArtistProfile.id == resource_id)
                    .where(Artist.organization_id == workspace_id)
                )
            ) is not None
        if kind == ResourceKind.campaign:
            return (
                await session.scalar(
                    select(Campaign.id)
                    .where(Campaign.id == resource_id)
                    .where(Campaign.organization_id == workspace_id)
                )
            ) is not None
        if kind == ResourceKind.analytics_metric_definition:
            return (
                await session.scalar(
                    select(AnalyticsMetricDefinition.id)
                    .where(AnalyticsMetricDefinition.id == resource_id)
                    .where(AnalyticsMetricDefinition.organization_id == workspace_id)
                )
            ) is not None
        if kind == ResourceKind.analytics_observation:
            return (
                await session.scalar(
                    select(AnalyticsObservation.id)
                    .where(AnalyticsObservation.id == resource_id)
                    .where(AnalyticsObservation.organization_id == workspace_id)
                )
            ) is not None

        return False

    async def _resource_action_is_authorized(
        self,
        session: AsyncSession,
        *,
        capability: Capability,
        membership: OrganizationMembership | LegacyWorkspaceAuthorizationMembership,
        workspace_membership: WorkspaceMembership,
        resource: AuthorizationResource | None,
    ) -> tuple[bool, str]:
        if (
            capability != Capability.artist_profile_edit
            or resource is None
            or str(resource.kind) != ResourceKind.artist_profile.value
            or not isinstance(resource.id, UUID)
        ):
            return True, "capability_allowed"

        target_profile_id = await session.scalar(
            select(ArtistProfile.universal_profile_id).where(
                ArtistProfile.id == resource.id
            )
        )
        if target_profile_id is None:
            return False, "invalid_resource_scope"
        if target_profile_id == workspace_membership.profile_id:
            return True, "capability_allowed"
        if membership.workspace_permission in {
            WorkspacePermission.owner,
            WorkspacePermission.admin,
        }:
            return True, "capability_allowed"

        for role in workspace_membership.roles:
            has_capability = any(
                capability_row.key == capability.value
                for capability_row in role.capabilities
            )
            if has_capability and role.key != "artist":
                return True, "capability_allowed"

        return False, "resource_owner_mismatch"

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

    def _actor_ref_from_input(
        self,
        actor: AuthorizationActorInput,
    ) -> AuthorizationActor:
        if isinstance(actor, UUID):
            return AuthorizationActor(
                kind=ActorKind.user,
                subject=str(actor),
                user_id=actor,
            )
        if isinstance(actor, User):
            return AuthorizationActor(
                kind=ActorKind.user,
                subject=str(actor.id),
                user_id=actor.id,
                display_name=actor.display_name,
            )
        return self._actor_ref(actor)

    def _workspace_id_from_input(
        self,
        actor: AuthorizationActorInput,
        workspace: AuthorizationWorkspace,
    ) -> UUID | None:
        if isinstance(workspace, MembershipContext):
            return workspace.workspace_id
        if isinstance(workspace, UUID):
            return workspace
        if isinstance(actor, UUID | User):
            return None
        return self._workspace_id(actor, workspace)

    def _normalize_action(
        self,
        action: AuthorizationAction,
    ) -> ResolvedAuthorizationAction:
        if isinstance(action, Capability | Permission):
            return action
        capability = self._normalize_capability(action)
        if capability is not None:
            return capability
        permission = self._normalize_permission(action)
        if permission is not None:
            return permission
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
    workspace: AuthorizationWorkspace | None = None,
    workspace_param: str | None = None,
    workspace_context: WorkspaceContextResolver | None = None,
    resource: AuthorizationResource | dict[str, Any] | None = None,
    resource_context: ResourceContextResolver | None = None,
    resource_kind: ResourceKind | str | None = None,
    resource_id_param: str | None = None,
    resource_workspace_param: str | None = None,
    department: str | None = None,
    hide_resource_existence: bool = False,
) -> Callable[..., CurrentUserContext]:
    required = (
        required_capability
        if isinstance(required_capability, Capability)
        else Capability(required_capability)
    )

    async def dependency(
        request: Request,
        session: SessionDep,
        context: Annotated[CurrentUserContext, Depends(require_workspace())],
    ) -> CurrentUserContext:
        resolved_workspace = workspace
        if workspace_context is not None:
            resolved_workspace = await _resolve_dependency_value(
                workspace_context,
                request,
                context,
            )
        elif workspace_param is not None:
            resolved_workspace = _request_uuid(request, workspace_param)
        if resolved_workspace is None:
            resolved_workspace = context.active_membership
        if resolved_workspace is None:
            raise _forbidden("Workspace context required")

        resolved_resource = resource
        if resource_context is not None:
            resolved_resource = await _resolve_dependency_value(
                resource_context,
                request,
                context,
            )
        elif (
            resource_kind is not None
            or resource_id_param is not None
            or resource_workspace_param is not None
            or department is not None
        ):
            resolved_resource = AuthorizationResource(
                kind=resource_kind,
                id=(
                    _request_uuid(request, resource_id_param)
                    if resource_id_param is not None
                    else None
                ),
                workspace_id=(
                    _request_uuid(request, resource_workspace_param)
                    if resource_workspace_param is not None
                    else None
                ),
                department=department,
            )

        decision = await authorization_service.decide_capability(
            session,
            actor=context,
            workspace=resolved_workspace,
            capability=required,
            resource=resolved_resource,
        )
        if decision.allowed:
            return context
        if hide_resource_existence and decision.reason in {
            "invalid_resource_scope",
            "membership_not_found",
        }:
            raise _not_found()
        if decision.reason == "insufficient_department_access":
            raise _forbidden("Insufficient department access")
        if decision.reason == "invalid_workspace":
            raise _forbidden("Workspace context required")
        raise _forbidden("Insufficient capability permission")

    return dependency
