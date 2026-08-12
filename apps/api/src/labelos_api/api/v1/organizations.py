import re
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from labelos_database.models import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    User,
)
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_api.activity import ActivityEventType, record_activity_event
from labelos_api.api.v1.onboarding import slugify_organization_name
from labelos_api.auth import (
    CurrentUserContext,
    SessionDep,
    get_current_user_context,
    has_role_at_least,
)
from labelos_api.authorization import Permission
from labelos_api.realtime import RealtimeEventType, RealtimePublisher
from labelos_api.workos_client import WorkOSAPIError, WorkOSClient, get_workos_client

router = APIRouter(prefix="/organizations", tags=["organizations"])

SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,118}[a-z0-9])?$"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


class OrganizationMemberRoleUpdateRequest(BaseModel):
    role: MembershipRole

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: MembershipRole) -> MembershipRole:
        if value is MembershipRole.owner:
            raise ValueError("Owner role changes are not supported")
        return value


class OrganizationMemberInviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: MembershipRole = MembershipRole.member

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(email):
            raise ValueError("Valid email is required")
        return email

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: MembershipRole) -> MembershipRole:
        if value is MembershipRole.owner:
            raise ValueError("Owner invitations are not supported")
        return value


class OrganizationInvitationAcceptRequest(BaseModel):
    invitation_token: str = Field(min_length=8, max_length=2048)

    @field_validator("invitation_token")
    @classmethod
    def validate_invitation_token(cls, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValueError("Invitation token is required")
        return token


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    role: MembershipRole
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
    role: MembershipRole
    status: str


class OrganizationInvitationResponse(BaseModel):
    id: str
    email: str
    role: MembershipRole
    state: str
    expires_at: str | None = None
    created_at: str | None = None


class OrganizationMembersListResponse(BaseModel):
    members: list[OrganizationMemberResponse]
    invitations: list[OrganizationInvitationResponse] = Field(default_factory=list)
    limit: int
    offset: int
    total: int


class OrganizationActivationResponse(BaseModel):
    organization: OrganizationResponse
    workos_organization_id: str


WorkOSClientDep = Annotated[WorkOSClient | None, Depends(get_workos_client)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _membership_for_context(
    context: CurrentUserContext,
    organization_id: UUID,
) -> MembershipRole | None:
    for membership in context.memberships:
        if (
            membership.organization_id == organization_id
            and membership.status == "active"
        ):
            return membership.role
    return None


def _require_membership(
    context: CurrentUserContext,
    organization_id: UUID,
    required_role: MembershipRole,
) -> MembershipRole:
    role = _membership_for_context(context, organization_id)
    if role is None:
        raise _not_found()
    if not has_role_at_least(role, required_role):
        raise _forbidden("Insufficient organization role")
    return role


def _require_permission(context: CurrentUserContext, permission: Permission) -> None:
    if permission.value not in context.principal.permissions:
        raise _forbidden("Insufficient permission")


def _require_active_organization(
    context: CurrentUserContext,
    organization_id: UUID,
) -> None:
    if context.active_organization_id != organization_id:
        raise _forbidden("Active organization mismatch")


def _organization_response(
    organization: Organization,
    role: MembershipRole,
) -> OrganizationResponse:
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        role=role,
        can_switch=organization.workos_organization_id is not None,
    )


async def _active_membership_row(
    session: AsyncSession,
    context: CurrentUserContext,
    organization_id: UUID,
) -> tuple[Organization, OrganizationMembership] | None:
    row = await session.execute(
        select(Organization, OrganizationMembership)
        .join(
            OrganizationMembership,
            OrganizationMembership.organization_id == Organization.id,
        )
        .where(Organization.id == organization_id)
        .where(OrganizationMembership.user_id == context.user.id)
        .where(OrganizationMembership.status == "active")
    )
    return row.one_or_none()


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


def _membership_role_from_workos(data: dict[str, Any]) -> MembershipRole:
    role = data.get("role")
    if isinstance(role, dict):
        slug = role.get("slug")
        if isinstance(slug, str) and slug in MembershipRole._value2member_map_:
            return MembershipRole(slug)
    role_slug = data.get("role_slug")
    if isinstance(role_slug, str) and role_slug in MembershipRole._value2member_map_:
        return MembershipRole(role_slug)
    return MembershipRole.member


def _safe_invitation_response(data: dict[str, Any]) -> OrganizationInvitationResponse:
    expires_at = data.get("expires_at")
    created_at = data.get("created_at")
    return OrganizationInvitationResponse(
        id=str(data["id"]),
        email=str(data["email"]).lower(),
        role=MembershipRole._value2member_map_.get(
            str(data.get("role_slug") or MembershipRole.member.value),
            MembershipRole.member,
        ),
        state=str(data.get("state") or "pending"),
        expires_at=expires_at if isinstance(expires_at, str) else None,
        created_at=created_at if isinstance(created_at, str) else None,
    )


async def _count_active_owners(
    session: AsyncSession,
    organization_id: UUID,
) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(OrganizationMembership)
            .where(OrganizationMembership.organization_id == organization_id)
            .where(OrganizationMembership.role == MembershipRole.owner)
            .where(OrganizationMembership.status == "active")
        )
        or 0
    )


async def _active_member_by_email(
    session: AsyncSession,
    organization_id: UUID,
    email: str,
) -> OrganizationMembership | None:
    return await session.scalar(
        select(OrganizationMembership)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(OrganizationMembership.organization_id == organization_id)
        .where(OrganizationMembership.status == "active")
        .where(func.lower(User.email) == email.lower())
    )


async def _sync_workos_membership(
    session: AsyncSession,
    *,
    organization: Organization,
    data: dict[str, Any],
) -> OrganizationMembership:
    workos_membership_id = str(data["id"])
    workos_user_id = str(data["user_id"])
    embedded_user = data.get("user")
    user = await session.scalar(
        select(User).where(User.workos_user_id == workos_user_id)
    )
    if user is None:
        embedded_email = (
            embedded_user.get("email") if isinstance(embedded_user, dict) else None
        )
        embedded_name = (
            embedded_user.get("name") if isinstance(embedded_user, dict) else None
        )
        email = (
            embedded_email
            if isinstance(embedded_email, str)
            else f"{workos_user_id}@workos.local"
        )
        user = User(
            workos_user_id=workos_user_id,
            email=email,
            display_name=(embedded_name if isinstance(embedded_name, str) else email),
        )
        session.add(user)
        await session.flush()
    elif isinstance(embedded_user, dict):
        if isinstance(embedded_user.get("email"), str):
            user.email = embedded_user["email"]
        if isinstance(embedded_user.get("name"), str):
            user.display_name = embedded_user["name"]

    membership = await session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.workos_membership_id == workos_membership_id
        )
    )
    if membership is None:
        membership = await session.scalar(
            select(OrganizationMembership)
            .where(OrganizationMembership.organization_id == organization.id)
            .where(OrganizationMembership.user_id == user.id)
        )

    role = _membership_role_from_workos(data)
    member_status = str(data.get("status") or "active")
    if membership is None:
        membership = OrganizationMembership(
            workos_membership_id=workos_membership_id,
            organization_id=organization.id,
            user_id=user.id,
            role=role,
            status=member_status,
        )
        session.add(membership)
    else:
        membership.workos_membership_id = workos_membership_id
        membership.role = role
        membership.status = member_status
    await session.flush()
    return membership


def _member_response(membership: OrganizationMembership) -> OrganizationMemberResponse:
    return OrganizationMemberResponse(
        id=membership.id,
        user_id=membership.user_id,
        email=membership.user.email,
        display_name=membership.user.display_name,
        role=membership.role,
        status=membership.status,
    )


def _require_workos_client(workos_client: WorkOSClient | None) -> WorkOSClient:
    if workos_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WorkOS API key is not configured",
        )
    return workos_client


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
        select(Organization, OrganizationMembership.role)
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
            _organization_response(organization, role)
            for organization, role in rows.all()
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
    role = _require_membership(context, organization_id, MembershipRole.viewer)
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise _not_found()
    return _organization_response(organization, role)


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

    await record_activity_event(
        session,
        event_type=ActivityEventType.organization_switched,
        operation="activate_organization",
        organization_id=organization.id,
        actor=context.user,
        entity_type="organization",
        entity_id=organization.id,
    )
    await session.commit()
    return OrganizationActivationResponse(
        organization=_organization_response(organization, membership.role),
        workos_organization_id=organization.workos_organization_id,
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
    session.add(
        OrganizationMembership(
            organization_id=organization.id,
            user_id=context.user.id,
            role=MembershipRole.owner,
            status="active",
        )
    )
    await record_activity_event(
        session,
        event_type=ActivityEventType.organization_created,
        operation="create_organization",
        organization_id=organization.id,
        actor=context.user,
        entity_type="organization",
        entity_id=organization.id,
        changes={
            "name": {"from": None, "to": organization.name},
            "slug": {"from": None, "to": organization.slug},
        },
    )
    await record_activity_event(
        session,
        event_type=ActivityEventType.member_joined,
        operation="create_owner_membership",
        organization_id=organization.id,
        actor=context.user,
        target_user_id=context.user.id,
        entity_type="member",
        entity_id=context.user.id,
        changes={"role": {"from": None, "to": MembershipRole.owner.value}},
        metadata={"membership_status": "active"},
    )

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
                organization, MembershipRole.owner
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
    return _organization_response(organization, MembershipRole.owner)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: UUID,
    payload: OrganizationUpdateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> OrganizationResponse:
    role = _require_membership(context, organization_id, MembershipRole.owner)
    _require_permission(context, Permission.organization_manage)

    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise _not_found()
    changes: dict[str, dict[str, str | None]] = {}
    if payload.slug is not None and payload.slug != organization.slug:
        if await _slug_exists(
            session,
            payload.slug,
            exclude_organization_id=organization_id,
        ):
            raise _conflict("Organization slug already exists")
        changes["slug"] = {"from": organization.slug, "to": payload.slug}
        organization.slug = payload.slug
    if payload.name is not None and payload.name != organization.name:
        changes["name"] = {"from": organization.name, "to": payload.name}
        organization.name = payload.name
    if changes:
        await record_activity_event(
            session,
            event_type=ActivityEventType.organization_updated,
            operation="update_organization",
            organization_id=organization.id,
            actor=context.user,
            entity_type="organization",
            entity_id=organization.id,
            changes=changes,
        )

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
            "organization": _organization_response(organization, role).model_dump(
                mode="json"
            )
        },
    )
    await session.commit()
    return _organization_response(organization, role)


@router.get(
    "/{organization_id}/members",
    response_model=OrganizationMembersListResponse,
)
async def list_organization_members(
    organization_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    workos_client: WorkOSClientDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrganizationMembersListResponse:
    _require_membership(context, organization_id, MembershipRole.admin)
    _require_permission(context, Permission.members_manage)

    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise _not_found()

    invitations: list[OrganizationInvitationResponse] = []
    if organization.workos_organization_id is not None:
        workos = _require_workos_client(workos_client)
        try:
            workos_invitations = await workos.list_invitations(
                organization_id=organization.workos_organization_id,
            )
        except WorkOSAPIError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="WorkOS invitations could not be loaded",
            ) from exc
        invitations = [
            _safe_invitation_response(invitation)
            for invitation in workos_invitations
            if invitation.get("state") == "pending"
        ]

    total = await session.scalar(
        select(func.count())
        .select_from(OrganizationMembership)
        .where(OrganizationMembership.organization_id == organization_id)
    )
    memberships = await session.scalars(
        select(OrganizationMembership)
        .options(selectinload(OrganizationMembership.user))
        .where(OrganizationMembership.organization_id == organization_id)
        .order_by(
            OrganizationMembership.created_at.asc(),
            OrganizationMembership.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return OrganizationMembersListResponse(
        members=[_member_response(membership) for membership in memberships.all()],
        invitations=invitations,
        limit=limit,
        offset=offset,
        total=total or 0,
    )


@router.post(
    "/{organization_id}/invitations",
    response_model=OrganizationInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_organization_member(
    organization_id: UUID,
    payload: OrganizationMemberInviteRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    workos_client: WorkOSClientDep,
) -> OrganizationInvitationResponse:
    _require_active_organization(context, organization_id)
    _require_membership(context, organization_id, MembershipRole.admin)
    _require_permission(context, Permission.members_manage)

    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise _not_found()
    if organization.workos_organization_id is None:
        raise _conflict("Organization is not connected to WorkOS")
    workos = _require_workos_client(workos_client)

    if await _active_member_by_email(session, organization_id, payload.email):
        raise _conflict("User is already an active member")

    try:
        existing_invitations = await workos.list_invitations(
            organization_id=organization.workos_organization_id,
            email=payload.email,
        )
    except WorkOSAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WorkOS invitations could not be checked",
        ) from exc
    pending = next(
        (
            invitation
            for invitation in existing_invitations
            if invitation.get("state") == "pending"
        ),
        None,
    )
    if pending is not None:
        raise _conflict("User already has a pending invitation")

    try:
        invitation = await workos.send_invitation(
            email=payload.email,
            organization_id=organization.workos_organization_id,
            role_slug=payload.role.value,
            inviter_user_id=context.principal.subject,
        )
    except WorkOSAPIError as exc:
        if exc.status_code == status.HTTP_409_CONFLICT:
            raise _conflict("User is already a member or invited") from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WorkOS invitation could not be sent",
        ) from exc

    response = _safe_invitation_response(invitation)
    await record_activity_event(
        session,
        event_type=ActivityEventType.member_invited,
        operation="invite_organization_member",
        organization_id=organization_id,
        actor=context.user,
        entity_type="invitation",
        entity_id=response.id,
        changes={"role": {"from": None, "to": response.role.value}},
        metadata={"invitation_id": response.id, "invitation_state": response.state},
    )
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.member_updated,
        actor=context.user,
        entity_type="invitation",
        entity_id=response.id,
        payload={"invitation": response.model_dump(mode="json")},
    )
    await session.commit()
    return response


@router.post("/join", response_model=OrganizationMemberResponse)
async def join_organization(
    payload: OrganizationInvitationAcceptRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    workos_client: WorkOSClientDep,
) -> OrganizationMemberResponse:
    workos = _require_workos_client(workos_client)
    try:
        invitation = await workos.find_invitation_by_token(payload.invitation_token)
    except WorkOSAPIError as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            raise _not_found() from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WorkOS invitation could not be loaded",
        ) from exc

    invite_email = str(invitation.get("email") or "").lower()
    current_email = context.user.email.lower()
    if invite_email != current_email:
        raise _forbidden("Invitation email does not match the signed-in user")
    if invitation.get("state") != "pending":
        raise _conflict("Invitation is not pending")

    workos_organization_id = invitation.get("organization_id")
    if not isinstance(workos_organization_id, str) or not workos_organization_id:
        raise _conflict("Invitation is not linked to an organization")

    organization = await session.scalar(
        select(Organization).where(
            Organization.workos_organization_id == workos_organization_id
        )
    )
    if organization is None:
        organization = Organization(
            name=workos_organization_id,
            slug=slugify_organization_name(workos_organization_id),
            workos_organization_id=workos_organization_id,
            owner_user_id=context.user.id,
        )
        session.add(organization)
        await session.flush()

    if await _active_member_by_email(session, organization.id, current_email):
        raise _conflict("User is already an active member")

    try:
        accepted = await workos.accept_invitation(str(invitation["id"]))
        workos_memberships = await workos.list_organization_memberships(
            organization_id=workos_organization_id,
            user_id=context.principal.subject,
            statuses=["active"],
        )
    except WorkOSAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WorkOS invitation could not be accepted",
        ) from exc

    membership_data = next(iter(workos_memberships), None)
    if membership_data is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WorkOS did not return an active organization membership",
        )

    membership = await _sync_workos_membership(
        session,
        organization=organization,
        data=membership_data,
    )
    membership.user_id = context.user.id
    await session.flush()
    await session.refresh(membership, ["user"])

    response = _member_response(membership)
    await record_activity_event(
        session,
        event_type=ActivityEventType.member_joined,
        operation="join_organization",
        organization_id=organization.id,
        actor=context.user,
        target_user_id=context.user.id,
        entity_type="member",
        entity_id=membership.id,
        changes={
            "role": {"from": None, "to": membership.role.value},
            "status": {"from": None, "to": membership.status},
        },
        metadata={
            "membership_id": membership.id,
            "workos_membership_id": membership.workos_membership_id,
            "invitation_id": str(accepted.get("id") or invitation["id"]),
        },
    )
    await RealtimePublisher(session).publish(
        organization_id=organization.id,
        event_type=RealtimeEventType.member_joined,
        actor=context.user,
        entity_type="member",
        entity_id=membership.id,
        payload={"member": response.model_dump(mode="json")},
    )
    await session.commit()
    return response


@router.patch(
    "/{organization_id}/members/{membership_id}",
    response_model=OrganizationMemberResponse,
)
async def update_organization_member_role(
    organization_id: UUID,
    membership_id: UUID,
    payload: OrganizationMemberRoleUpdateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    workos_client: WorkOSClientDep,
) -> OrganizationMemberResponse:
    _require_active_organization(context, organization_id)
    _require_membership(context, organization_id, MembershipRole.owner)
    _require_permission(context, Permission.members_manage)

    membership = await session.scalar(
        select(OrganizationMembership)
        .options(selectinload(OrganizationMembership.user))
        .where(OrganizationMembership.id == membership_id)
        .where(OrganizationMembership.organization_id == organization_id)
    )
    if membership is None:
        raise _not_found()
    if membership.status != "active":
        raise _conflict("Only active member roles can be updated")
    if membership.role is MembershipRole.owner:
        raise _conflict("Owner role changes are not supported")
    if membership.user_id == context.user.id:
        raise _conflict("You cannot change your own role")
    if membership.workos_membership_id is None:
        raise _conflict("Member is not connected to WorkOS")
    workos = _require_workos_client(workos_client)

    try:
        workos_membership = await workos.update_organization_membership(
            membership_id=membership.workos_membership_id,
            role_slug=payload.role.value,
        )
    except WorkOSAPIError as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            raise _not_found() from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WorkOS membership could not be updated",
        ) from exc

    previous_role = membership.role
    membership.role = _membership_role_from_workos(workos_membership)
    await record_activity_event(
        session,
        event_type=ActivityEventType.member_role_changed,
        operation="update_organization_member_role",
        organization_id=organization_id,
        actor=context.user,
        target_user_id=membership.user_id,
        entity_type="member",
        entity_id=membership.id,
        changes={"role": {"from": previous_role.value, "to": membership.role.value}},
        metadata={
            "membership_id": membership.id,
            "workos_membership_id": membership.workos_membership_id,
        },
    )

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict("Member conflicts with an existing record") from exc

    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.member_updated,
        actor=context.user,
        entity_type="member",
        entity_id=membership.id,
        payload={"member": _member_response(membership).model_dump(mode="json")},
    )
    await session.commit()
    return _member_response(membership)


@router.delete(
    "/{organization_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_organization_member(
    organization_id: UUID,
    membership_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    workos_client: WorkOSClientDep,
) -> None:
    _require_active_organization(context, organization_id)
    _require_membership(context, organization_id, MembershipRole.owner)
    _require_permission(context, Permission.members_manage)

    membership = await session.scalar(
        select(OrganizationMembership)
        .options(selectinload(OrganizationMembership.user))
        .where(OrganizationMembership.id == membership_id)
        .where(OrganizationMembership.organization_id == organization_id)
    )
    if membership is None:
        raise _not_found()
    if membership.user_id == context.user.id:
        raise _conflict("You cannot remove yourself")
    if (
        membership.role is MembershipRole.owner
        and await _count_active_owners(session, organization_id) <= 1
    ):
        raise _conflict("Cannot remove the final owner")
    if membership.workos_membership_id is None:
        raise _conflict("Member is not connected to WorkOS")
    workos = _require_workos_client(workos_client)

    target_user_id = membership.user_id
    workos_membership_id = membership.workos_membership_id
    try:
        await workos.delete_organization_membership(workos_membership_id)
    except WorkOSAPIError as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            raise _not_found() from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WorkOS membership could not be removed",
        ) from exc

    await session.delete(membership)
    await record_activity_event(
        session,
        event_type=ActivityEventType.member_removed,
        operation="remove_organization_member",
        organization_id=organization_id,
        actor=context.user,
        target_user_id=target_user_id,
        entity_type="member",
        entity_id=membership_id,
        changes={"status": {"from": membership.status, "to": "removed"}},
        metadata={
            "membership_id": membership_id,
            "workos_membership_id": workos_membership_id,
            "role": membership.role.value,
        },
    )
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.member_removed,
        actor=context.user,
        entity_type="member",
        entity_id=membership_id,
        payload={"membership_id": str(membership_id), "user_id": str(target_user_id)},
    )
    await session.commit()
