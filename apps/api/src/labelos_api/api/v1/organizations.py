import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from labelos_database.departments import (
    DEFAULT_DEPARTMENTS,
    DEFAULT_ROLE_DEPARTMENT_ACCESS,
)
from labelos_database.models import (
    Department,
    MembershipDepartmentAccess,
    MembershipProfessionalRole,
    MembershipRole,
    Organization,
    OrganizationMembership,
    ProfessionalRole,
    Role,
    RoleCapability,
    UniversalProfile,
    WorkspaceInvite,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspacePermission,
)
from labelos_database.roles import DEFAULT_ROLES
from labelos_database.workspace_memberships import (
    ensure_workspace_membership_for_organization_membership,
    get_or_create_profile_for_user,
)
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_api.api.v1.onboarding import slugify_organization_name
from labelos_api.auth import (
    CurrentUserContext,
    SessionDep,
    get_current_user_context,
)
from labelos_api.authorization import Capability, authorization_service
from labelos_api.realtime import RealtimeEventType, RealtimePublisher

router = APIRouter(prefix="/organizations", tags=["organizations"])

SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,118}[a-z0-9])?$"
ALLOWED_PROFESSIONAL_ROLES = {
    "artist": "Artist",
    "producer": "Producer",
    "songwriter": "Songwriter",
    "management": "Management",
    "a&r": "A&R",
    "legal": "Legal",
    "marketing": "Marketing",
    "finance": "Finance",
}
ALLOWED_WORKSPACE_ROLES = {
    default_role.key: default_role.display_name for default_role in DEFAULT_ROLES
}
WORKSPACE_ROLE_ALIASES = {
    "a&r": "a_and_r",
    "management": "manager",
}
ALLOWED_DEPARTMENT_ACCESS = {
    department.slug: department.display_name for department in DEFAULT_DEPARTMENTS
}


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=SLUG_PATTERN,
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Organization name is required")
        return name


class OrganizationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=SLUG_PATTERN,
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("Organization name is required")
        return name

    @model_validator(mode="after")
    def require_update(self) -> "OrganizationUpdateRequest":
        if self.name is None and self.slug is None:
            raise ValueError("At least one organization field is required")
        return self


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    workspace_permission: WorkspacePermission
    role: WorkspacePermission
    department_access: list[str] = Field(default_factory=list)
    capability_permissions: list[str] = Field(default_factory=list)
    can_switch: bool = False


class OrganizationsListResponse(BaseModel):
    organizations: list[OrganizationResponse]
    limit: int
    offset: int
    total: int


class OrganizationMemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    display_name: str | None
    workspace_permission: WorkspacePermission
    role: WorkspacePermission
    professional_roles: list[str] = Field(default_factory=list)
    department_access: list[str] = Field(default_factory=list)
    pending_department_access: list[str] = Field(default_factory=list)
    denied_department_access: list[str] = Field(default_factory=list)
    capability_permissions: list[str] = Field(default_factory=list)
    status: str


class OrganizationMembersListResponse(BaseModel):
    members: list[OrganizationMemberResponse]
    limit: int
    offset: int
    total: int


class WorkspaceRoleAssignmentCreateRequest(BaseModel):
    role_id: UUID
    metadata: dict[str, Any] | None = None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and not isinstance(value, dict):
            raise ValueError("metadata must be an object")
        return value


class WorkspaceRoleAssignmentsReplaceRequest(BaseModel):
    role_ids: list[UUID] = Field(default_factory=list, max_length=32)

    @field_validator("role_ids")
    @classmethod
    def deduplicate_role_ids(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))


class WorkspaceRoleResponse(BaseModel):
    id: UUID
    key: str
    display_name: str
    description: str
    system_role: bool


class AuthorizationRoleSummaryResponse(BaseModel):
    key: str
    name: str


class AuthorizationContextResponse(BaseModel):
    workspace_id: UUID
    roles: list[AuthorizationRoleSummaryResponse] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class WorkspaceRoleDefinitionResponse(BaseModel):
    id: UUID
    key: str
    name: str
    description: str
    system_role: bool
    capabilities: list[str] = Field(default_factory=list)


class WorkspaceRolesListResponse(BaseModel):
    roles: list[WorkspaceRoleDefinitionResponse]


class MemberRoleAssignmentSummaryResponse(BaseModel):
    member_id: UUID
    roles: list[AuthorizationRoleSummaryResponse] = Field(default_factory=list)


class MemberRoleAssignmentsListResponse(BaseModel):
    assignments: list[MemberRoleAssignmentSummaryResponse]


class WorkspaceRoleAssignmentResponse(BaseModel):
    id: UUID
    membership_id: UUID
    role: WorkspaceRoleResponse
    assigned_by: UUID | None
    assigned_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class WorkspaceRoleAssignmentsListResponse(BaseModel):
    roles: list[WorkspaceRoleAssignmentResponse]


class OrganizationActivationResponse(BaseModel):
    organization: OrganizationResponse
    workos_organization_id: str


class WorkspaceInviteCreateRequest(BaseModel):
    email: str | None = Field(default=None, min_length=3, max_length=320)
    professional_roles: list[str] = Field(default_factory=list, max_length=8)
    workspace_roles: list[str] = Field(default_factory=list, max_length=8)
    department_access: list[str] | None = Field(default=None, max_length=32)
    expires_in_days: int = Field(default=7, ge=1, le=90)
    maximum_uses: int | None = Field(default=None, ge=1, le=1000)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        email = value.strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("Invite email is required")
        return email

    @field_validator("professional_roles")
    @classmethod
    def validate_professional_roles(cls, value: list[str]) -> list[str]:
        return _normalize_professional_roles(value)

    @field_validator("workspace_roles")
    @classmethod
    def validate_workspace_roles(cls, value: list[str]) -> list[str]:
        return _normalize_workspace_roles(value)

    @field_validator("department_access")
    @classmethod
    def validate_department_access(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_department_access(value)

    @model_validator(mode="after")
    def default_workspace_roles_from_professional_roles(
        self,
    ) -> "WorkspaceInviteCreateRequest":
        if not self.workspace_roles and self.professional_roles:
            self.workspace_roles = _normalize_workspace_roles(self.professional_roles)
        return self


class WorkspaceInviteAcceptRequest(BaseModel):
    professional_roles: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("professional_roles")
    @classmethod
    def validate_professional_roles(cls, value: list[str]) -> list[str]:
        return _normalize_professional_roles(value)


class WorkspaceInviteWorkspaceResponse(BaseModel):
    id: UUID
    name: str
    slug: str


class WorkspaceInviteInviterResponse(BaseModel):
    id: UUID
    email: str
    display_name: str | None


class WorkspaceInviteResponse(BaseModel):
    id: UUID
    token: str
    email: str | None
    workspace: WorkspaceInviteWorkspaceResponse
    inviter: WorkspaceInviteInviterResponse | None
    professional_roles: list[str] = Field(default_factory=list)
    workspace_roles: list[str] = Field(default_factory=list)
    proposed_department_access: list[str] = Field(default_factory=list)
    expiration: datetime
    maximum_uses: int | None
    use_count: int
    status: str
    join_path: str


class WorkspaceInviteAcceptResponse(BaseModel):
    workspace: WorkspaceInviteWorkspaceResponse
    membership_id: UUID
    status: str


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _gone(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_410_GONE, detail=detail)


def _membership_for_context(
    context: CurrentUserContext,
    organization_id: UUID,
) -> WorkspacePermission | None:
    for membership in context.memberships:
        if (
            membership.organization_id == organization_id
            and membership.status == "active"
        ):
            return membership.workspace_permission
    return None


def _require_membership(
    context: CurrentUserContext,
    organization_id: UUID,
) -> WorkspacePermission:
    workspace_permission = _membership_for_context(context, organization_id)
    if workspace_permission is None:
        raise _not_found()
    return workspace_permission


def _require_capability(
    context: CurrentUserContext,
    organization_id: UUID,
    capability: Capability,
) -> None:
    if capability not in authorization_service.effective_capabilities(
        context,
        workspace=organization_id,
    ):
        raise _forbidden("Insufficient capability permission")


def _require_role_capabilities_administerable(
    context: CurrentUserContext,
    organization_id: UUID,
    role: Role,
) -> None:
    if role.workspace_id not in {None, organization_id}:
        raise _not_found()
    actor_capabilities = authorization_service.effective_capabilities(
        context,
        workspace=organization_id,
    )
    role_capabilities = {
        Capability(capability.key)
        for capability in role.capabilities
        if capability.key in Capability._value2member_map_
    }
    if not role_capabilities.issubset(actor_capabilities):
        raise _forbidden("Cannot administer a role with forbidden capabilities")


def _organization_response(
    organization: Organization,
    workspace_permission: WorkspacePermission,
    *,
    department_access: list[str] | None = None,
    capability_permissions: list[str] | None = None,
) -> OrganizationResponse:
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        workspace_permission=workspace_permission,
        role=workspace_permission,
        department_access=department_access or [],
        capability_permissions=capability_permissions or [],
        can_switch=organization.workos_organization_id is not None,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _invite_status(invite: WorkspaceInvite) -> str:
    if invite.status != "active":
        return invite.status
    if _as_utc(invite.expires_at) <= _utc_now():
        return "expired"
    if invite.maximum_uses is not None and invite.use_count >= invite.maximum_uses:
        return "exhausted"
    return "active"


def _require_usable_invite(invite: WorkspaceInvite) -> None:
    effective_status = _invite_status(invite)
    if effective_status != "active":
        if effective_status == "expired" and invite.status == "active":
            invite.status = "expired"
        raise _gone("Invite is no longer available")


def _professional_role_slug(value: str) -> str:
    slug = "".join(
        character.lower() if character.isalnum() or character == "&" else "_"
        for character in value.strip()
    ).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "other"


def _normalize_professional_roles(value: list[str]) -> list[str]:
    normalized_roles: list[str] = []
    seen: set[str] = set()

    for role in value:
        normalized = _professional_role_slug(role)
        if normalized not in ALLOWED_PROFESSIONAL_ROLES:
            raise ValueError("Unsupported professional role")
        if normalized in seen:
            continue
        normalized_roles.append(ALLOWED_PROFESSIONAL_ROLES[normalized])
        seen.add(normalized)

    return normalized_roles


def _normalize_workspace_roles(value: list[str]) -> list[str]:
    normalized_roles: list[str] = []
    seen: set[str] = set()

    for role in value:
        normalized = _professional_role_slug(role)
        normalized = WORKSPACE_ROLE_ALIASES.get(normalized, normalized)
        if normalized not in ALLOWED_WORKSPACE_ROLES:
            raise ValueError("Unsupported workspace role")
        if normalized in seen:
            continue
        normalized_roles.append(normalized)
        seen.add(normalized)

    return normalized_roles


def _normalize_department_slug(value: str) -> str:
    slug = "".join(
        character.lower() if character.isalnum() or character == "&" else "_"
        for character in value.strip()
    ).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug


def _normalize_department_access(value: list[str]) -> list[str]:
    normalized_departments: list[str] = []
    seen: set[str] = set()

    for department in value:
        normalized = _normalize_department_slug(department)
        if normalized not in ALLOWED_DEPARTMENT_ACCESS:
            raise ValueError("Unsupported department access")
        if normalized in seen:
            continue
        normalized_departments.append(normalized)
        seen.add(normalized)

    return normalized_departments


def _proposed_department_access_for_roles(role_names: list[str]) -> list[str]:
    department_slugs: list[str] = []
    seen: set[str] = set()

    for role_name in role_names:
        role_slug = _professional_role_slug(role_name)
        for department_slug in DEFAULT_ROLE_DEPARTMENT_ACCESS.get(role_slug, []):
            if department_slug in seen:
                continue
            department_slugs.append(department_slug)
            seen.add(department_slug)

    return department_slugs


async def _get_or_create_professional_role(
    session: AsyncSession,
    display_name: str,
) -> ProfessionalRole:
    slug = _professional_role_slug(display_name)
    role = await session.scalar(
        select(ProfessionalRole).where(
            (ProfessionalRole.slug == slug)
            | (func.lower(ProfessionalRole.display_name) == display_name.lower())
        )
    )
    if role is not None:
        return role

    role = ProfessionalRole(
        slug=slug,
        display_name=display_name,
        description=f"{display_name} professional role.",
        default_department_access=list(DEFAULT_ROLE_DEPARTMENT_ACCESS.get(slug, [])),
    )
    session.add(role)
    await session.flush()
    return role


async def _get_or_create_department(
    session: AsyncSession,
    slug: str,
) -> Department:
    department = await session.scalar(select(Department).where(Department.slug == slug))
    if department is not None:
        return department

    default_department = next(
        (department for department in DEFAULT_DEPARTMENTS if department.slug == slug),
        None,
    )
    display_name = (
        default_department.display_name
        if default_department is not None
        else slug.replace("_", " ").title()
    )
    description = (
        default_department.description
        if default_department is not None
        else f"{display_name} department."
    )
    access_sensitivity = (
        default_department.access_sensitivity.value
        if default_department is not None
        else "standard"
    )
    department = Department(
        slug=slug,
        display_name=display_name,
        description=description,
        access_sensitivity=access_sensitivity,
    )
    session.add(department)
    await session.flush()
    return department


async def _replace_membership_professional_roles(
    session: AsyncSession,
    membership: OrganizationMembership,
    role_names: list[str],
) -> None:
    await session.execute(
        delete(MembershipProfessionalRole).where(
            MembershipProfessionalRole.membership_id == membership.id
        )
    )
    await session.flush()

    for index, role_name in enumerate(role_names):
        professional_role = await _get_or_create_professional_role(session, role_name)
        session.add(
            MembershipProfessionalRole(
                membership_id=membership.id,
                professional_role_id=professional_role.id,
                is_primary=index == 0,
                status="active",
            )
        )


async def _replace_membership_department_access(
    session: AsyncSession,
    membership: OrganizationMembership,
    department_slugs: list[str],
    *,
    approved_by: UUID | None,
) -> None:
    await session.execute(
        delete(MembershipDepartmentAccess).where(
            MembershipDepartmentAccess.membership_id == membership.id
        )
    )
    await session.flush()

    membership.department_access = list(department_slugs)
    approved_at = _utc_now() if approved_by is not None else None
    for department_slug in department_slugs:
        department = await _get_or_create_department(session, department_slug)
        session.add(
            MembershipDepartmentAccess(
                membership_id=membership.id,
                department_id=department.id,
                access_level="member",
                source="invitation",
                approved_by=approved_by,
                approved_at=approved_at,
            )
        )


async def _assign_workspace_roles(
    session: AsyncSession,
    *,
    workspace_membership: WorkspaceMembership,
    role_keys: list[str],
    assigned_by: UUID | None,
) -> list[Role]:
    if not role_keys:
        return []

    roles = (await session.scalars(select(Role).where(Role.key.in_(role_keys)))).all()
    roles_by_key = {role.key: role for role in roles}
    missing_roles = [role_key for role_key in role_keys if role_key not in roles_by_key]
    if missing_roles:
        raise _conflict("Invite references unavailable workspace roles")

    existing_role_ids = set(
        (
            await session.scalars(
                select(WorkspaceMembershipRole.role_id).where(
                    WorkspaceMembershipRole.membership_id == workspace_membership.id
                )
            )
        ).all()
    )
    assigned_roles: list[Role] = []
    for role_key in role_keys:
        role = roles_by_key[role_key]
        assigned_roles.append(role)
        if role.id in existing_role_ids:
            continue
        session.add(
            WorkspaceMembershipRole(
                membership_id=workspace_membership.id,
                role_id=role.id,
                assigned_by=assigned_by,
                assigned_at=_utc_now(),
                metadata_json={"source": "workspace_invite"},
            )
        )
        existing_role_ids.add(role.id)
    await session.flush()
    return assigned_roles


def _workspace_invite_response(invite: WorkspaceInvite) -> WorkspaceInviteResponse:
    status_value = _invite_status(invite)
    return WorkspaceInviteResponse(
        id=invite.id,
        token=invite.token,
        email=invite.invitee_email,
        workspace=WorkspaceInviteWorkspaceResponse(
            id=invite.organization.id,
            name=invite.organization.name,
            slug=invite.organization.slug,
        ),
        inviter=(
            WorkspaceInviteInviterResponse(
                id=invite.inviter.id,
                email=invite.inviter.email,
                display_name=invite.inviter.display_name,
            )
            if invite.inviter is not None
            else None
        ),
        professional_roles=list(invite.professional_roles),
        workspace_roles=list(invite.workspace_roles),
        proposed_department_access=list(invite.proposed_department_access),
        expiration=invite.expires_at,
        maximum_uses=invite.maximum_uses,
        use_count=invite.use_count,
        status=status_value,
        join_path=f"/join/{invite.token}",
    )


def _role_assignment_response(
    assignment: WorkspaceMembershipRole,
) -> WorkspaceRoleAssignmentResponse:
    return WorkspaceRoleAssignmentResponse(
        id=assignment.id,
        membership_id=assignment.membership_id,
        role=WorkspaceRoleResponse(
            id=assignment.role.id,
            key=assignment.role.key,
            display_name=assignment.role.display_name,
            description=assignment.role.description,
            system_role=assignment.role.system_role,
        ),
        assigned_by=assignment.assigned_by,
        assigned_at=assignment.assigned_at,
        metadata=assignment.metadata_json,
        created_at=assignment.created_at,
    )


def _role_display_name_from_key(role_key: str) -> str:
    return ALLOWED_WORKSPACE_ROLES.get(role_key, role_key.replace("_", " ").title())


def _role_summary(role: Role) -> AuthorizationRoleSummaryResponse:
    return AuthorizationRoleSummaryResponse(key=role.key, name=role.display_name)


def _role_capability_keys(role: Role) -> list[str]:
    return sorted({capability.key for capability in role.capabilities})


def _workspace_role_definition_response(role: Role) -> WorkspaceRoleDefinitionResponse:
    return WorkspaceRoleDefinitionResponse(
        id=role.id,
        key=role.key,
        name=role.display_name,
        description=role.description,
        system_role=role.system_role,
        capabilities=_role_capability_keys(role),
    )


async def _load_current_workspace_roles(
    session: AsyncSession,
    *,
    context: CurrentUserContext,
    organization_id: UUID,
) -> list[AuthorizationRoleSummaryResponse]:
    workspace_membership = await session.scalar(
        select(WorkspaceMembership)
        .join(WorkspaceMembership.profile)
        .options(
            selectinload(WorkspaceMembership.role_assignments).selectinload(
                WorkspaceMembershipRole.role
            )
        )
        .where(WorkspaceMembership.workspace_id == organization_id)
        .where(WorkspaceMembership.status == "active")
        .where(UniversalProfile.user_id == context.user.id)
    )
    role_by_key = {
        membership.workspace_permission.value: AuthorizationRoleSummaryResponse(
            key=membership.workspace_permission.value,
            name=_role_display_name_from_key(membership.workspace_permission.value),
        )
        for membership in context.memberships
        if membership.workspace_id == organization_id and membership.status == "active"
    }
    if workspace_membership is not None:
        for role in workspace_membership.roles:
            role_by_key[role.key] = _role_summary(role)
    return [role_by_key[key] for key in sorted(role_by_key)]


def _member_role_assignment_summary(
    membership: OrganizationMembership,
) -> MemberRoleAssignmentSummaryResponse:
    workspace_membership = membership.workspace_membership
    roles = (
        []
        if workspace_membership is None
        else [_role_summary(role) for role in workspace_membership.roles]
    )
    roles_by_key = {role.key: role for role in roles}
    return MemberRoleAssignmentSummaryResponse(
        member_id=membership.id,
        roles=[roles_by_key[key] for key in sorted(roles_by_key)],
    )


def _member_role_payload(
    *,
    membership: OrganizationMembership,
    role: Role,
    action: str,
) -> dict[str, Any]:
    return {
        "action": action,
        "membershipId": str(membership.id),
        "userId": str(membership.user_id),
        "name": membership.user.display_name or membership.user.email,
        "displayName": membership.user.display_name,
        "email": membership.user.email,
        "roleId": str(role.id),
        "role": role.display_name,
        "roleKey": role.key,
    }


def _profile_role_payload(
    *,
    profile_id: UUID,
    workspace_id: UUID,
    membership: OrganizationMembership,
    role: Role,
) -> dict[str, Any]:
    return {
        "profileId": str(profile_id),
        "workspaceId": str(workspace_id),
        "membershipId": str(membership.id),
        "roleId": str(role.id),
        "role": role.display_name,
        "roleKey": role.key,
    }


def _profile_roles_updated_payload(
    *,
    profile_id: UUID,
    workspace_id: UUID,
    membership: OrganizationMembership,
    action: str,
    role: Role | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "profileId": str(profile_id),
        "workspaceId": str(workspace_id),
        "membershipId": str(membership.id),
        "action": action,
    }
    if role is not None:
        payload.update(
            {
                "roleId": str(role.id),
                "role": role.display_name,
                "roleKey": role.key,
            }
        )
    return payload


def _authorization_role_audit_payload(
    *,
    workspace_id: UUID,
    membership: OrganizationMembership,
    workspace_membership: WorkspaceMembership,
    role: Role,
    action: str,
) -> dict[str, Any]:
    return {
        "action": action,
        "workspaceId": str(workspace_id),
        "membershipId": str(membership.id),
        "workspaceMembershipId": str(workspace_membership.id),
        "memberUserId": str(membership.user_id),
        "profileId": str(workspace_membership.profile_id),
        "roleId": str(role.id),
        "roleKey": role.key,
        "role": role.display_name,
    }


def _authorization_roles_updated_audit_payload(
    *,
    workspace_id: UUID,
    membership: OrganizationMembership,
    workspace_membership: WorkspaceMembership,
    action: str,
    assigned_roles: list[Role] | None = None,
    removed_roles: list[Role] | None = None,
) -> dict[str, Any]:
    return {
        "action": action,
        "workspaceId": str(workspace_id),
        "membershipId": str(membership.id),
        "workspaceMembershipId": str(workspace_membership.id),
        "memberUserId": str(membership.user_id),
        "profileId": str(workspace_membership.profile_id),
        "assignedRoles": [
            {"roleId": str(role.id), "roleKey": role.key, "role": role.display_name}
            for role in assigned_roles or []
        ],
        "removedRoles": [
            {"roleId": str(role.id), "roleKey": role.key, "role": role.display_name}
            for role in removed_roles or []
        ],
    }


def _profile_workspace_payload(
    *,
    profile_id: UUID,
    workspace_id: UUID,
    membership_id: UUID,
    status: str,
) -> dict[str, Any]:
    return {
        "profileId": str(profile_id),
        "workspaceId": str(workspace_id),
        "membershipId": str(membership_id),
        "status": status,
    }


async def _workspace_membership_for_organization_member(
    session: AsyncSession,
    *,
    organization_id: UUID,
    member_id: UUID,
    ensure: bool = True,
    active_only: bool = False,
) -> tuple[OrganizationMembership, WorkspaceMembership | None]:
    membership = await session.scalar(
        select(OrganizationMembership)
        .options(selectinload(OrganizationMembership.user))
        .where(OrganizationMembership.id == member_id)
        .where(OrganizationMembership.organization_id == organization_id)
    )
    if membership is None:
        raise _not_found()
    if active_only and membership.status != "active":
        raise _not_found()

    workspace_membership = await session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.organization_membership_id == membership.id)
        .where(WorkspaceMembership.workspace_id == organization_id)
    )
    if (
        active_only
        and workspace_membership is not None
        and workspace_membership.status != "active"
    ):
        raise _not_found()
    if workspace_membership is None and ensure:
        workspace_membership = (
            await ensure_workspace_membership_for_organization_membership(
                session,
                membership,
            )
        )
    return membership, workspace_membership


async def _active_membership_row(
    session: AsyncSession,
    context: CurrentUserContext,
    organization_id: UUID,
) -> tuple[Organization, OrganizationMembership] | None:
    row = await session.execute(
        select(Organization, OrganizationMembership)
        .options(
            selectinload(OrganizationMembership.department_access_grants),
            selectinload(OrganizationMembership.department_access_grants).selectinload(
                MembershipDepartmentAccess.department
            ),
        )
        .join(
            OrganizationMembership,
            OrganizationMembership.organization_id == Organization.id,
        )
        .where(Organization.id == organization_id)
        .where(OrganizationMembership.user_id == context.user.id)
        .where(OrganizationMembership.status == "active")
    )
    return row.one_or_none()


async def _active_owner_count(
    session: AsyncSession,
    organization_id: UUID,
) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(OrganizationMembership)
        .where(OrganizationMembership.organization_id == organization_id)
        .where(OrganizationMembership.status == "active")
        .where(OrganizationMembership.workspace_permission == WorkspacePermission.owner)
    )
    return count or 0


async def _active_owner_access_count_excluding_member(
    session: AsyncSession,
    organization_id: UUID,
    member_id: UUID,
) -> int:
    owner_membership_ids = {
        membership_id
        for membership_id in (
            await session.scalars(
                select(OrganizationMembership.id)
                .where(OrganizationMembership.organization_id == organization_id)
                .where(OrganizationMembership.status == "active")
                .where(OrganizationMembership.id != member_id)
                .where(
                    OrganizationMembership.workspace_permission
                    == WorkspacePermission.owner
                )
            )
        ).all()
    }
    owner_role_membership_ids = {
        membership_id
        for membership_id in (
            await session.scalars(
                select(OrganizationMembership.id)
                .join(
                    WorkspaceMembership,
                    WorkspaceMembership.organization_membership_id
                    == OrganizationMembership.id,
                )
                .join(
                    WorkspaceMembershipRole,
                    WorkspaceMembershipRole.membership_id == WorkspaceMembership.id,
                )
                .join(Role, Role.id == WorkspaceMembershipRole.role_id)
                .where(OrganizationMembership.organization_id == organization_id)
                .where(OrganizationMembership.status == "active")
                .where(WorkspaceMembership.status == "active")
                .where(OrganizationMembership.id != member_id)
                .where(Role.key == WorkspacePermission.owner.value)
            )
        ).all()
    }
    return len(owner_membership_ids | owner_role_membership_ids)


async def _slug_exists(
    session: AsyncSession,
    slug: str,
    *,
    exclude_organization_id: UUID | None = None,
) -> bool:
    statement = select(Organization.id).where(Organization.slug == slug)
    if exclude_organization_id is not None:
        statement = statement.where(Organization.id != exclude_organization_id)
    return await session.scalar(statement) is not None


async def _workspace_invite_by_token(
    session: AsyncSession,
    token: str,
) -> WorkspaceInvite | None:
    return await session.scalar(
        select(WorkspaceInvite)
        .options(
            selectinload(WorkspaceInvite.organization),
            selectinload(WorkspaceInvite.inviter),
        )
        .where(WorkspaceInvite.token == token)
    )


@router.get("", response_model=OrganizationsListResponse)
async def list_organizations(
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrganizationsListResponse:
    total = await session.scalar(
        select(func.count())
        .select_from(OrganizationMembership)
        .where(OrganizationMembership.user_id == context.user.id)
        .where(OrganizationMembership.status == "active")
    )
    rows = await session.execute(
        select(Organization, OrganizationMembership)
        .options(
            selectinload(OrganizationMembership.department_access_grants),
            selectinload(OrganizationMembership.department_access_grants).selectinload(
                MembershipDepartmentAccess.department
            ),
        )
        .join(
            OrganizationMembership,
            OrganizationMembership.organization_id == Organization.id,
        )
        .where(OrganizationMembership.user_id == context.user.id)
        .where(OrganizationMembership.status == "active")
        .order_by(Organization.name.asc(), Organization.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return OrganizationsListResponse(
        organizations=[
            _organization_response(
                organization,
                membership.workspace_permission,
                department_access=list(membership.approved_department_access),
                capability_permissions=list(membership.capability_permissions),
            )
            for organization, membership in rows.all()
        ],
        limit=limit,
        offset=offset,
        total=total or 0,
    )


@router.get("/current", response_model=OrganizationResponse)
async def get_current_organization(
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> OrganizationResponse:
    organization_id = context.active_organization_id
    if organization_id is None:
        raise _forbidden("Organization context required")
    workspace_permission = _require_membership(context, organization_id)
    membership = context.active_membership
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise _not_found()
    return _organization_response(
        organization,
        workspace_permission,
        department_access=list(membership.department_access) if membership else [],
        capability_permissions=(
            list(membership.capability_permissions) if membership else []
        ),
    )


@router.post(
    "/{organization_id}/activate",
    response_model=OrganizationActivationResponse,
)
async def activate_organization(
    organization_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> OrganizationActivationResponse:
    row = await _active_membership_row(session, context, organization_id)
    if row is None:
        raise _not_found()

    organization, membership = row
    if organization.workos_organization_id is None:
        raise _conflict("Organization is not connected to WorkOS")

    return OrganizationActivationResponse(
        organization=_organization_response(
            organization,
            membership.workspace_permission,
            department_access=list(membership.approved_department_access),
            capability_permissions=list(membership.capability_permissions),
        ),
        workos_organization_id=organization.workos_organization_id,
    )


@router.post(
    "/{organization_id}/invites",
    response_model=WorkspaceInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_invite(
    organization_id: UUID,
    payload: WorkspaceInviteCreateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> WorkspaceInviteResponse:
    _require_capability(context, organization_id, Capability.workspace_member_invite)
    if payload.workspace_roles:
        _require_capability(
            context,
            organization_id,
            Capability.workspace_member_roles_manage,
        )
        _require_capability(context, organization_id, Capability.role_assign)

    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise _not_found()

    if payload.workspace_roles:
        roles = (
            await session.scalars(
                select(Role)
                .options(
                    selectinload(Role.capability_links).selectinload(
                        RoleCapability.capability
                    )
                )
                .where(Role.key.in_(payload.workspace_roles))
            )
        ).all()
        roles_by_key = {role.key: role for role in roles}
        for role_key in payload.workspace_roles:
            role = roles_by_key.get(role_key)
            if role is None:
                raise _conflict("Invite references unavailable workspace roles")
            _require_role_capabilities_administerable(
                context,
                organization_id,
                role,
            )

    if payload.email is not None:
        duplicate_invite = await session.scalar(
            select(WorkspaceInvite)
            .where(WorkspaceInvite.organization_id == organization_id)
            .where(WorkspaceInvite.invitee_email == payload.email)
            .where(WorkspaceInvite.status == "active")
            .where(WorkspaceInvite.expires_at > _utc_now())
        )
        if duplicate_invite is not None:
            raise _conflict("An active invite already exists for this email")

    for _attempt in range(5):
        proposed_department_access = (
            payload.department_access
            if payload.department_access is not None
            else _proposed_department_access_for_roles(payload.professional_roles)
        )
        invite = WorkspaceInvite(
            token=secrets.token_urlsafe(9),
            organization_id=organization_id,
            inviter_user_id=context.user.id,
            invitee_email=payload.email,
            professional_roles=payload.professional_roles,
            workspace_roles=payload.workspace_roles,
            proposed_department_access=proposed_department_access,
            expires_at=_utc_now() + timedelta(days=payload.expires_in_days),
            maximum_uses=payload.maximum_uses,
            status="active",
        )
        session.add(invite)
        try:
            await session.flush()
            await RealtimePublisher(session).publish(
                organization_id=organization_id,
                event_type=RealtimeEventType.invitation_sent,
                actor=context.user,
                entity_type="invitation",
                entity_id=invite.id,
                payload={
                    "inviteId": str(invite.id),
                    "workspaceId": str(organization_id),
                    "professionalRoles": list(invite.professional_roles),
                    "workspaceRoles": list(invite.workspace_roles),
                    "departmentAccess": list(invite.proposed_department_access),
                    "expiresAt": invite.expires_at.isoformat(),
                },
            )
            await session.commit()
            await session.refresh(invite, attribute_names=["organization", "inviter"])
            return _workspace_invite_response(invite)
        except IntegrityError:
            await session.rollback()

    raise _conflict("Could not create a unique invite link")


@router.get("/invites/{token}", response_model=WorkspaceInviteResponse)
async def get_workspace_invite(
    token: str,
    session: SessionDep,
) -> WorkspaceInviteResponse:
    invite = await _workspace_invite_by_token(session, token)
    if invite is None:
        raise _not_found()
    if _invite_status(invite) == "expired" and invite.status == "active":
        invite.status = "expired"
        await session.commit()
    return _workspace_invite_response(invite)


@router.post(
    "/invites/{token}/accept",
    response_model=WorkspaceInviteAcceptResponse,
)
async def accept_workspace_invite(
    token: str,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    payload: Annotated[WorkspaceInviteAcceptRequest | None, Body()] = None,
) -> WorkspaceInviteAcceptResponse:
    invite = await _workspace_invite_by_token(session, token)
    if invite is None:
        raise _not_found()

    _require_usable_invite(invite)

    membership = await session.scalar(
        select(OrganizationMembership)
        .where(OrganizationMembership.organization_id == invite.organization_id)
        .where(OrganizationMembership.user_id == context.user.id)
    )
    membership_activated = False
    if membership is None:
        membership = OrganizationMembership(
            organization_id=invite.organization_id,
            user_id=context.user.id,
            role=MembershipRole.member,
            workspace_permission=WorkspacePermission.member,
            status="active",
        )
        session.add(membership)
        invite.use_count += 1
        membership_activated = True
    elif membership.status != "active":
        membership.status = "active"
        membership.role = MembershipRole.member
        membership.workspace_permission = WorkspacePermission.member
        invite.use_count += 1
        membership_activated = True
    await session.flush()
    existing_profile_id = await session.scalar(
        select(UniversalProfile.id).where(UniversalProfile.user_id == context.user.id)
    )
    inviter_profile_id = None
    if invite.inviter is not None:
        inviter_profile = await get_or_create_profile_for_user(session, invite.inviter)
        inviter_profile_id = inviter_profile.id
    workspace_membership = (
        await ensure_workspace_membership_for_organization_membership(
            session,
            membership,
            invited_by_profile_id=inviter_profile_id,
        )
    )

    invite_roles = list(invite.professional_roles)
    accepted_roles = invite_roles or (
        payload.professional_roles if payload is not None else []
    )
    if accepted_roles:
        await _replace_membership_professional_roles(
            session,
            membership,
            accepted_roles,
        )
    workspace_role_keys = list(invite.workspace_roles) or _normalize_workspace_roles(
        accepted_roles
    )
    assigned_workspace_roles = await _assign_workspace_roles(
        session,
        workspace_membership=workspace_membership,
        role_keys=workspace_role_keys,
        assigned_by=invite.inviter_user_id,
    )
    invited_department_access = list(invite.proposed_department_access)
    if invited_department_access:
        await _replace_membership_department_access(
            session,
            membership,
            invited_department_access,
            approved_by=invite.inviter_user_id,
        )

    if _invite_status(invite) == "exhausted":
        invite.status = "exhausted"

    try:
        if existing_profile_id is None:
            await RealtimePublisher(session).publish(
                organization_id=invite.organization_id,
                event_type=RealtimeEventType.profile_created,
                actor=context.user,
                entity_type="profile",
                entity_id=workspace_membership.profile_id,
                payload={
                    "profileId": str(workspace_membership.profile_id),
                    "workspaceId": str(invite.organization_id),
                },
            )
        if membership_activated:
            await RealtimePublisher(session).publish(
                organization_id=invite.organization_id,
                event_type=RealtimeEventType.profile_workspace_joined,
                actor=context.user,
                entity_type="profile",
                entity_id=workspace_membership.profile_id,
                payload=_profile_workspace_payload(
                    profile_id=workspace_membership.profile_id,
                    workspace_id=invite.organization_id,
                    membership_id=membership.id,
                    status=membership.status,
                ),
            )
            await RealtimePublisher(session).publish(
                organization_id=invite.organization_id,
                event_type=RealtimeEventType.profile_membership_updated,
                actor=context.user,
                entity_type="profile",
                entity_id=workspace_membership.profile_id,
                payload=_profile_workspace_payload(
                    profile_id=workspace_membership.profile_id,
                    workspace_id=invite.organization_id,
                    membership_id=membership.id,
                    status=membership.status,
                ),
            )
            await RealtimePublisher(session).publish(
                organization_id=invite.organization_id,
                event_type=RealtimeEventType.invitation_accepted,
                actor=context.user,
                entity_type="invitation",
                entity_id=invite.id,
                payload={
                    "inviteId": str(invite.id),
                    "profileId": str(workspace_membership.profile_id),
                    "workspaceId": str(invite.organization_id),
                    "membershipId": str(membership.id),
                    "professionalRoles": accepted_roles,
                    "workspaceRoles": [
                        {"id": str(role.id), "key": role.key, "name": role.display_name}
                        for role in assigned_workspace_roles
                    ],
                },
            )
        await RealtimePublisher(session).publish(
            organization_id=invite.organization_id,
            event_type=RealtimeEventType.member_joined,
            actor=invite.inviter,
            entity_type="member",
            entity_id=membership.id,
            payload={
                "membershipId": str(membership.id),
                "userId": str(membership.user_id),
                "email": context.user.email,
                "status": membership.status,
                "professionalRoles": accepted_roles,
                "workspaceRoles": [
                    {"id": str(role.id), "key": role.key, "name": role.display_name}
                    for role in assigned_workspace_roles
                ],
                "inviteId": str(invite.id),
            },
        )
        if accepted_roles or assigned_workspace_roles:
            await RealtimePublisher(session).publish(
                organization_id=invite.organization_id,
                event_type=RealtimeEventType.profile_roles_updated,
                actor=context.user,
                entity_type="profile",
                entity_id=workspace_membership.profile_id,
                payload={
                    "profileId": str(workspace_membership.profile_id),
                    "workspaceId": str(invite.organization_id),
                    "membershipId": str(membership.id),
                    "action": "assigned",
                    "professionalRoles": accepted_roles,
                    "workspaceRoles": [
                        {"id": str(role.id), "key": role.key, "name": role.display_name}
                        for role in assigned_workspace_roles
                    ],
                },
            )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict("Invite could not be accepted") from exc

    return WorkspaceInviteAcceptResponse(
        workspace=WorkspaceInviteWorkspaceResponse(
            id=invite.organization.id,
            name=invite.organization.name,
            slug=invite.organization.slug,
        ),
        membership_id=membership.id,
        status=membership.status,
    )


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    payload: OrganizationCreateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> OrganizationResponse:
    slug = payload.slug or slugify_organization_name(payload.name)
    if await _slug_exists(session, slug):
        raise _conflict("Organization slug already exists")

    organization = Organization(
        name=payload.name,
        slug=slug,
        owner_user_id=context.user.id,
    )
    session.add(organization)
    await session.flush()
    owner_membership = OrganizationMembership(
        organization_id=organization.id,
        user_id=context.user.id,
        role=MembershipRole.owner,
        workspace_permission=WorkspacePermission.owner,
        status="active",
    )
    session.add(owner_membership)
    await session.flush()
    existing_profile_id = await session.scalar(
        select(UniversalProfile.id).where(UniversalProfile.user_id == context.user.id)
    )
    workspace_membership = (
        await ensure_workspace_membership_for_organization_membership(
            session,
            owner_membership,
        )
    )
    departments = (
        await session.scalars(select(Department).where(Department.is_active.is_(True)))
    ).all()
    for department in departments:
        session.add(
            MembershipDepartmentAccess(
                membership_id=owner_membership.id,
                department_id=department.id,
                access_level="owner",
                source="workspace_owner",
                approved_by=context.user.id,
                approved_at=datetime.now(UTC),
            )
        )

    try:
        if existing_profile_id is None:
            await RealtimePublisher(session).publish(
                organization_id=organization.id,
                event_type=RealtimeEventType.profile_created,
                actor=context.user,
                entity_type="profile",
                entity_id=workspace_membership.profile_id,
                payload={
                    "profileId": str(workspace_membership.profile_id),
                    "workspaceId": str(organization.id),
                },
            )
        await RealtimePublisher(session).publish(
            organization_id=organization.id,
            event_type=RealtimeEventType.profile_workspace_joined,
            actor=context.user,
            entity_type="profile",
            entity_id=workspace_membership.profile_id,
            payload=_profile_workspace_payload(
                profile_id=workspace_membership.profile_id,
                workspace_id=organization.id,
                membership_id=owner_membership.id,
                status=owner_membership.status,
            ),
        )
        await RealtimePublisher(session).publish(
            organization_id=organization.id,
            event_type=RealtimeEventType.profile_membership_updated,
            actor=context.user,
            entity_type="profile",
            entity_id=workspace_membership.profile_id,
            payload=_profile_workspace_payload(
                profile_id=workspace_membership.profile_id,
                workspace_id=organization.id,
                membership_id=owner_membership.id,
                status=owner_membership.status,
            ),
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict("Organization conflicts with an existing record") from exc

    await RealtimePublisher(session).publish(
        organization_id=organization.id,
        event_type=RealtimeEventType.organization_updated,
        actor=context.user,
        entity_type="organization",
        entity_id=organization.id,
        payload={
            "organization": _organization_response(
                organization, WorkspacePermission.owner
            ).model_dump(mode="json")
        },
    )
    await RealtimePublisher(session).publish(
        organization_id=organization.id,
        event_type=RealtimeEventType.member_joined,
        actor=context.user,
        entity_type="member",
        entity_id=context.user.id,
        payload={"role": MembershipRole.owner.value, "status": "active"},
    )
    await session.commit()
    return _organization_response(organization, WorkspacePermission.owner)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: UUID,
    payload: OrganizationUpdateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> OrganizationResponse:
    workspace_permission = _require_membership(context, organization_id)
    _require_capability(context, organization_id, Capability.workspace_update)

    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise _not_found()
    if payload.slug is not None and payload.slug != organization.slug:
        if await _slug_exists(
            session,
            payload.slug,
            exclude_organization_id=organization_id,
        ):
            raise _conflict("Organization slug already exists")
        organization.slug = payload.slug
    if payload.name is not None:
        organization.name = payload.name

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict("Organization conflicts with an existing record") from exc

    await RealtimePublisher(session).publish(
        organization_id=organization.id,
        event_type=RealtimeEventType.organization_updated,
        actor=context.user,
        entity_type="organization",
        entity_id=organization.id,
        payload={
            "organization": _organization_response(
                organization,
                workspace_permission,
            ).model_dump(mode="json")
        },
    )
    await session.commit()
    return _organization_response(organization, workspace_permission)


@router.get(
    "/{organization_id}/members",
    response_model=OrganizationMembersListResponse,
)
async def list_organization_members(
    organization_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrganizationMembersListResponse:
    if await _active_membership_row(session, context, organization_id) is None:
        raise _not_found()
    _require_capability(context, organization_id, Capability.workspace_member_view)

    total = await session.scalar(
        select(func.count())
        .select_from(OrganizationMembership)
        .where(OrganizationMembership.organization_id == organization_id)
    )
    memberships = await session.scalars(
        select(OrganizationMembership)
        .options(
            selectinload(OrganizationMembership.user),
            selectinload(OrganizationMembership.professional_role_links).selectinload(
                MembershipProfessionalRole.professional_role
            ),
            selectinload(OrganizationMembership.department_access_grants),
            selectinload(OrganizationMembership.department_access_grants).selectinload(
                MembershipDepartmentAccess.department
            ),
        )
        .where(OrganizationMembership.organization_id == organization_id)
        .order_by(
            OrganizationMembership.created_at.asc(),
            OrganizationMembership.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return OrganizationMembersListResponse(
        members=[
            OrganizationMemberResponse(
                id=membership.id,
                user_id=membership.user_id,
                email=membership.user.email,
                display_name=membership.user.display_name,
                workspace_permission=membership.workspace_permission,
                role=membership.workspace_permission,
                professional_roles=list(membership.professional_roles),
                department_access=list(membership.approved_department_access),
                pending_department_access=list(membership.pending_department_access),
                denied_department_access=[],
                capability_permissions=list(membership.capability_permissions),
                status=membership.status,
            )
            for membership in memberships.all()
        ],
        limit=limit,
        offset=offset,
        total=total or 0,
    )


@router.get(
    "/{organization_id}/authorization/context",
    response_model=AuthorizationContextResponse,
)
async def get_current_authorization_context(
    organization_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> AuthorizationContextResponse:
    if await _active_membership_row(session, context, organization_id) is None:
        raise _not_found()

    capabilities = authorization_service.effective_capabilities(
        context,
        workspace=organization_id,
    )
    return AuthorizationContextResponse(
        workspace_id=organization_id,
        roles=await _load_current_workspace_roles(
            session,
            context=context,
            organization_id=organization_id,
        ),
        capabilities=sorted(capability.value for capability in capabilities),
    )


@router.get(
    "/{organization_id}/roles",
    response_model=WorkspaceRolesListResponse,
)
async def list_workspace_roles(
    organization_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> WorkspaceRolesListResponse:
    if await _active_membership_row(session, context, organization_id) is None:
        raise _not_found()
    _require_capability(context, organization_id, Capability.role_view)

    roles = await session.scalars(
        select(Role)
        .options(
            selectinload(Role.capability_links).selectinload(RoleCapability.capability)
        )
        .where((Role.workspace_id.is_(None)) | (Role.workspace_id == organization_id))
        .order_by(
            Role.workspace_id.asc(),
            Role.key.asc(),
            Role.id.asc(),
        )
    )
    return WorkspaceRolesListResponse(
        roles=[_workspace_role_definition_response(role) for role in roles.all()]
    )


@router.get(
    "/{organization_id}/member-role-assignments",
    response_model=MemberRoleAssignmentsListResponse,
)
async def list_member_role_assignments(
    organization_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> MemberRoleAssignmentsListResponse:
    if await _active_membership_row(session, context, organization_id) is None:
        raise _not_found()
    _require_capability(context, organization_id, Capability.workspace_member_view)

    memberships = await session.scalars(
        select(OrganizationMembership)
        .options(
            selectinload(OrganizationMembership.workspace_membership)
            .selectinload(WorkspaceMembership.role_assignments)
            .selectinload(WorkspaceMembershipRole.role)
        )
        .where(OrganizationMembership.organization_id == organization_id)
        .where(OrganizationMembership.status == "active")
        .order_by(
            OrganizationMembership.created_at.asc(),
            OrganizationMembership.id.asc(),
        )
    )
    return MemberRoleAssignmentsListResponse(
        assignments=[
            _member_role_assignment_summary(membership)
            for membership in memberships.all()
        ]
    )


@router.get(
    "/{organization_id}/members/{member_id}/roles",
    response_model=WorkspaceRoleAssignmentsListResponse,
)
async def list_member_workspace_roles(
    organization_id: UUID,
    member_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> WorkspaceRoleAssignmentsListResponse:
    if await _active_membership_row(session, context, organization_id) is None:
        raise _not_found()
    _require_capability(context, organization_id, Capability.workspace_member_view)

    _membership, workspace_membership = (
        await _workspace_membership_for_organization_member(
            session,
            organization_id=organization_id,
            member_id=member_id,
            ensure=False,
        )
    )
    if workspace_membership is None:
        return WorkspaceRoleAssignmentsListResponse(roles=[])
    assignments = await session.scalars(
        select(WorkspaceMembershipRole)
        .options(selectinload(WorkspaceMembershipRole.role))
        .where(WorkspaceMembershipRole.membership_id == workspace_membership.id)
        .order_by(
            WorkspaceMembershipRole.assigned_at.asc(),
            WorkspaceMembershipRole.role_id.asc(),
        )
    )
    return WorkspaceRoleAssignmentsListResponse(
        roles=[
            _role_assignment_response(assignment) for assignment in assignments.all()
        ]
    )


@router.put(
    "/{organization_id}/members/{member_id}/roles",
    response_model=WorkspaceRoleAssignmentsListResponse,
)
async def replace_member_workspace_roles(
    organization_id: UUID,
    member_id: UUID,
    payload: WorkspaceRoleAssignmentsReplaceRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> WorkspaceRoleAssignmentsListResponse:
    if await _active_membership_row(session, context, organization_id) is None:
        raise _not_found()
    _require_capability(
        context,
        organization_id,
        Capability.workspace_member_roles_manage,
    )
    _require_capability(context, organization_id, Capability.role_assign)

    membership, workspace_membership = (
        await _workspace_membership_for_organization_member(
            session,
            organization_id=organization_id,
            member_id=member_id,
            active_only=True,
        )
    )
    if workspace_membership is None:
        raise _not_found()
    if membership.user_id == context.user.id:
        raise _forbidden("Cannot replace workspace roles for yourself")

    existing_assignments = list(
        (
            await session.scalars(
                select(WorkspaceMembershipRole)
                .options(selectinload(WorkspaceMembershipRole.role))
                .where(WorkspaceMembershipRole.membership_id == workspace_membership.id)
            )
        ).all()
    )
    requested_role_ids = set(payload.role_ids)
    roles: list[Role] = []
    if requested_role_ids:
        roles = list(
            (
                await session.scalars(
                    select(Role)
                    .options(
                        selectinload(Role.capability_links).selectinload(
                            RoleCapability.capability
                        )
                    )
                    .where(Role.id.in_(requested_role_ids))
                )
            ).all()
        )
    if len(roles) != len(requested_role_ids):
        raise _not_found()
    for role in roles:
        _require_role_capabilities_administerable(context, organization_id, role)

    requested_owner = any(role.key == WorkspacePermission.owner.value for role in roles)
    target_has_owner_access = (
        membership.workspace_permission == WorkspacePermission.owner
        or any(
            assignment.role is not None
            and assignment.role.key == WorkspacePermission.owner.value
            for assignment in existing_assignments
        )
    )
    if (
        target_has_owner_access
        and not requested_owner
        and await _active_owner_access_count_excluding_member(
            session,
            organization_id,
            member_id,
        )
        == 0
    ):
        raise _conflict("Cannot remove the last workspace owner role")

    existing_by_role_id = {
        assignment.role_id: assignment for assignment in existing_assignments
    }
    requested_by_role_id = {role.id: role for role in roles}
    roles_to_add = [role for role in roles if role.id not in existing_by_role_id]
    assignments_to_remove = [
        assignment
        for assignment in existing_assignments
        if assignment.role_id not in requested_by_role_id
    ]

    try:
        for assignment in assignments_to_remove:
            await session.delete(assignment)
        for role in roles_to_add:
            session.add(
                WorkspaceMembershipRole(
                    membership_id=workspace_membership.id,
                    role_id=role.id,
                    assigned_by=context.user.id,
                    assigned_at=_utc_now(),
                    metadata_json={"source": "workspace_settings"},
                )
            )
        await session.flush()

        for assignment in assignments_to_remove:
            role = assignment.role
            await RealtimePublisher(session).publish(
                organization_id=organization_id,
                event_type=RealtimeEventType.member_role_changed,
                actor=context.user,
                entity_type="member",
                entity_id=membership.id,
                payload=_member_role_payload(
                    membership=membership,
                    role=role,
                    action="removed",
                ),
            )
            await RealtimePublisher(session).publish(
                organization_id=organization_id,
                event_type=RealtimeEventType.role_removed,
                actor=context.user,
                entity_type="workspace_membership",
                entity_id=workspace_membership.id,
                payload=_authorization_role_audit_payload(
                    workspace_id=organization_id,
                    membership=membership,
                    workspace_membership=workspace_membership,
                    role=role,
                    action="removed",
                ),
            )
            await RealtimePublisher(session).publish(
                organization_id=organization_id,
                event_type=RealtimeEventType.profile_role_removed,
                actor=context.user,
                entity_type="profile",
                entity_id=workspace_membership.profile_id,
                payload=_profile_role_payload(
                    profile_id=workspace_membership.profile_id,
                    workspace_id=organization_id,
                    membership=membership,
                    role=role,
                ),
            )
        for role in roles_to_add:
            await RealtimePublisher(session).publish(
                organization_id=organization_id,
                event_type=RealtimeEventType.member_role_changed,
                actor=context.user,
                entity_type="member",
                entity_id=membership.id,
                payload=_member_role_payload(
                    membership=membership,
                    role=role,
                    action="assigned",
                ),
            )
            await RealtimePublisher(session).publish(
                organization_id=organization_id,
                event_type=RealtimeEventType.role_assigned,
                actor=context.user,
                entity_type="workspace_membership",
                entity_id=workspace_membership.id,
                payload=_authorization_role_audit_payload(
                    workspace_id=organization_id,
                    membership=membership,
                    workspace_membership=workspace_membership,
                    role=role,
                    action="assigned",
                ),
            )
            await RealtimePublisher(session).publish(
                organization_id=organization_id,
                event_type=RealtimeEventType.profile_role_added,
                actor=context.user,
                entity_type="profile",
                entity_id=workspace_membership.profile_id,
                payload=_profile_role_payload(
                    profile_id=workspace_membership.profile_id,
                    workspace_id=organization_id,
                    membership=membership,
                    role=role,
                ),
            )
        if assignments_to_remove or roles_to_add:
            await RealtimePublisher(session).publish(
                organization_id=organization_id,
                event_type=RealtimeEventType.membership_roles_updated,
                actor=context.user,
                entity_type="workspace_membership",
                entity_id=workspace_membership.id,
                payload=_authorization_roles_updated_audit_payload(
                    workspace_id=organization_id,
                    membership=membership,
                    workspace_membership=workspace_membership,
                    action="replaced",
                    assigned_roles=roles_to_add,
                    removed_roles=[
                        assignment.role for assignment in assignments_to_remove
                    ],
                ),
            )
            await RealtimePublisher(session).publish(
                organization_id=organization_id,
                event_type=RealtimeEventType.profile_roles_updated,
                actor=context.user,
                entity_type="profile",
                entity_id=workspace_membership.profile_id,
                payload=_profile_roles_updated_payload(
                    profile_id=workspace_membership.profile_id,
                    workspace_id=organization_id,
                    membership=membership,
                    action="replaced",
                ),
            )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict("Workspace role assignment conflict") from exc

    assignments = await session.scalars(
        select(WorkspaceMembershipRole)
        .options(selectinload(WorkspaceMembershipRole.role))
        .where(WorkspaceMembershipRole.membership_id == workspace_membership.id)
        .order_by(
            WorkspaceMembershipRole.assigned_at.asc(),
            WorkspaceMembershipRole.role_id.asc(),
        )
    )
    return WorkspaceRoleAssignmentsListResponse(
        roles=[
            _role_assignment_response(assignment) for assignment in assignments.all()
        ]
    )


@router.post(
    "/{organization_id}/members/{member_id}/roles",
    response_model=WorkspaceRoleAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_member_workspace_role(
    organization_id: UUID,
    member_id: UUID,
    payload: WorkspaceRoleAssignmentCreateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> WorkspaceRoleAssignmentResponse:
    if await _active_membership_row(session, context, organization_id) is None:
        raise _not_found()
    _require_capability(
        context,
        organization_id,
        Capability.workspace_member_roles_manage,
    )
    _require_capability(context, organization_id, Capability.role_assign)

    membership, workspace_membership = (
        await _workspace_membership_for_organization_member(
            session,
            organization_id=organization_id,
            member_id=member_id,
            active_only=True,
        )
    )
    if workspace_membership is None:
        raise _not_found()
    if membership.user_id == context.user.id:
        raise _forbidden("Cannot assign workspace roles to yourself")
    role = await session.scalar(
        select(Role)
        .options(
            selectinload(Role.capability_links).selectinload(RoleCapability.capability)
        )
        .where(Role.id == payload.role_id)
    )
    if role is None:
        raise _not_found()
    _require_role_capabilities_administerable(context, organization_id, role)

    existing_assignment = await session.scalar(
        select(WorkspaceMembershipRole)
        .where(WorkspaceMembershipRole.membership_id == workspace_membership.id)
        .where(WorkspaceMembershipRole.role_id == role.id)
    )
    if existing_assignment is not None:
        raise _conflict("Workspace role is already assigned to this member")

    assignment = WorkspaceMembershipRole(
        membership_id=workspace_membership.id,
        role_id=role.id,
        assigned_by=context.user.id,
        assigned_at=_utc_now(),
        metadata_json=payload.metadata or {},
    )
    session.add(assignment)
    try:
        await session.flush()
        await RealtimePublisher(session).publish(
            organization_id=organization_id,
            event_type=RealtimeEventType.member_role_changed,
            actor=context.user,
            entity_type="member",
            entity_id=membership.id,
            payload=_member_role_payload(
                membership=membership,
                role=role,
                action="assigned",
            ),
        )
        await RealtimePublisher(session).publish(
            organization_id=organization_id,
            event_type=RealtimeEventType.role_assigned,
            actor=context.user,
            entity_type="workspace_membership",
            entity_id=workspace_membership.id,
            payload=_authorization_role_audit_payload(
                workspace_id=organization_id,
                membership=membership,
                workspace_membership=workspace_membership,
                role=role,
                action="assigned",
            ),
        )
        await RealtimePublisher(session).publish(
            organization_id=organization_id,
            event_type=RealtimeEventType.profile_role_added,
            actor=context.user,
            entity_type="profile",
            entity_id=workspace_membership.profile_id,
            payload=_profile_role_payload(
                profile_id=workspace_membership.profile_id,
                workspace_id=organization_id,
                membership=membership,
                role=role,
            ),
        )
        await RealtimePublisher(session).publish(
            organization_id=organization_id,
            event_type=RealtimeEventType.membership_roles_updated,
            actor=context.user,
            entity_type="workspace_membership",
            entity_id=workspace_membership.id,
            payload=_authorization_roles_updated_audit_payload(
                workspace_id=organization_id,
                membership=membership,
                workspace_membership=workspace_membership,
                action="assigned",
                assigned_roles=[role],
            ),
        )
        await RealtimePublisher(session).publish(
            organization_id=organization_id,
            event_type=RealtimeEventType.profile_roles_updated,
            actor=context.user,
            entity_type="profile",
            entity_id=workspace_membership.profile_id,
            payload=_profile_roles_updated_payload(
                profile_id=workspace_membership.profile_id,
                workspace_id=organization_id,
                membership=membership,
                action="assigned",
                role=role,
            ),
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict("Workspace role is already assigned to this member") from exc

    assignment.role = role
    return _role_assignment_response(assignment)


@router.delete(
    "/{organization_id}/members/{member_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member_workspace_role(
    organization_id: UUID,
    member_id: UUID,
    role_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> None:
    if await _active_membership_row(session, context, organization_id) is None:
        raise _not_found()
    _require_capability(
        context,
        organization_id,
        Capability.workspace_member_roles_manage,
    )
    _require_capability(context, organization_id, Capability.role_assign)

    membership, workspace_membership = (
        await _workspace_membership_for_organization_member(
            session,
            organization_id=organization_id,
            member_id=member_id,
            active_only=True,
        )
    )
    if workspace_membership is None:
        raise _not_found()
    if membership.user_id == context.user.id:
        raise _forbidden("Cannot remove workspace roles from yourself")
    assignment = await session.scalar(
        select(WorkspaceMembershipRole)
        .options(
            selectinload(WorkspaceMembershipRole.role)
            .selectinload(Role.capability_links)
            .selectinload(RoleCapability.capability)
        )
        .where(WorkspaceMembershipRole.membership_id == workspace_membership.id)
        .where(WorkspaceMembershipRole.role_id == role_id)
    )
    if assignment is None:
        raise _not_found()

    role = assignment.role
    _require_role_capabilities_administerable(context, organization_id, role)
    await session.delete(assignment)
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.member_role_changed,
        actor=context.user,
        entity_type="member",
        entity_id=membership.id,
        payload=_member_role_payload(
            membership=membership,
            role=role,
            action="removed",
        ),
    )
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.role_removed,
        actor=context.user,
        entity_type="workspace_membership",
        entity_id=workspace_membership.id,
        payload=_authorization_role_audit_payload(
            workspace_id=organization_id,
            membership=membership,
            workspace_membership=workspace_membership,
            role=role,
            action="removed",
        ),
    )
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.profile_role_removed,
        actor=context.user,
        entity_type="profile",
        entity_id=workspace_membership.profile_id,
        payload=_profile_role_payload(
            profile_id=workspace_membership.profile_id,
            workspace_id=organization_id,
            membership=membership,
            role=role,
        ),
    )
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.membership_roles_updated,
        actor=context.user,
        entity_type="workspace_membership",
        entity_id=workspace_membership.id,
        payload=_authorization_roles_updated_audit_payload(
            workspace_id=organization_id,
            membership=membership,
            workspace_membership=workspace_membership,
            action="removed",
            removed_roles=[role],
        ),
    )
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.profile_roles_updated,
        actor=context.user,
        entity_type="profile",
        entity_id=workspace_membership.profile_id,
        payload=_profile_roles_updated_payload(
            profile_id=workspace_membership.profile_id,
            workspace_id=organization_id,
            membership=membership,
            action="removed",
            role=role,
        ),
    )
    await session.commit()


@router.delete(
    "/{organization_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_organization_member(
    organization_id: UUID,
    member_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> None:
    if await _active_membership_row(session, context, organization_id) is None:
        raise _not_found()
    _require_capability(context, organization_id, Capability.workspace_member_remove)

    membership, workspace_membership = (
        await _workspace_membership_for_organization_member(
            session,
            organization_id=organization_id,
            member_id=member_id,
            active_only=True,
        )
    )
    if workspace_membership is None:
        raise _not_found()
    if (
        membership.workspace_permission == WorkspacePermission.owner
        and await _active_owner_count(session, organization_id) <= 1
    ):
        raise _conflict("Cannot remove the last workspace owner")

    membership.status = "removed"
    workspace_membership.status = "removed"
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.member_removed,
        actor=context.user,
        entity_type="member",
        entity_id=membership.id,
        payload={
            "membershipId": str(membership.id),
            "userId": str(membership.user_id),
            "workspaceId": str(organization_id),
            "status": membership.status,
        },
    )
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.profile_membership_updated,
        actor=context.user,
        entity_type="profile",
        entity_id=workspace_membership.profile_id,
        payload=_profile_workspace_payload(
            profile_id=workspace_membership.profile_id,
            workspace_id=organization_id,
            membership_id=membership.id,
            status=membership.status,
        ),
    )
    await session.commit()
