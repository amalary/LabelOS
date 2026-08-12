from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from labelos_database.models import MembershipRole, Organization, OrganizationMembership
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_api.api.v1.onboarding import slugify_organization_name
from labelos_api.auth import (
    CurrentUserContext,
    SessionDep,
    get_current_user_context,
    has_role_at_least,
)
from labelos_api.authorization import Permission
from labelos_api.realtime import RealtimeEventType, RealtimePublisher

router = APIRouter(prefix="/organizations", tags=["organizations"])

SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,118}[a-z0-9])?$"


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


class OrganizationMembersListResponse(BaseModel):
    members: list[OrganizationMemberResponse]
    limit: int
    offset: int
    total: int


class OrganizationActivationResponse(BaseModel):
    organization: OrganizationResponse
    workos_organization_id: str


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
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrganizationMembersListResponse:
    _require_membership(context, organization_id, MembershipRole.admin)
    _require_permission(context, Permission.members_manage)

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
        members=[
            OrganizationMemberResponse(
                id=membership.id,
                user_id=membership.user_id,
                email=membership.user.email,
                display_name=membership.user.display_name,
                role=membership.role,
                status=membership.status,
            )
            for membership in memberships.all()
        ],
        limit=limit,
        offset=offset,
        total=total or 0,
    )
