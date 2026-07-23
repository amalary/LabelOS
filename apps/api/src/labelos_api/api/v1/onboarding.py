from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from labelos_database.models import MembershipRole, Organization, OrganizationMembership
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class WorkspaceSyncRequest(BaseModel):
    workos_organization_id: str = Field(min_length=1, max_length=255)
    organization_name: str = Field(min_length=1, max_length=200)
    workos_membership_id: str | None = Field(default=None, max_length=255)
    membership_status: str = Field(default="active", min_length=1, max_length=60)


class WorkspaceSyncResponse(BaseModel):
    organization_id: str
    organization_slug: str
    membership_role: MembershipRole


def slugify_organization_name(name: str) -> str:
    normalized = name.strip().lower()
    chars: list[str] = []
    previous_dash = False
    for char in normalized:
        if char.isalnum():
            chars.append(char)
            previous_dash = False
        elif not previous_dash:
            chars.append("-")
            previous_dash = True

    slug = "".join(chars).strip("-")
    return slug[:120] or "workspace"


async def unique_organization_slug(
    session: AsyncSession,
    base_slug: str,
    workos_organization_id: str,
) -> str:
    suffix = workos_organization_id.lower().replace("_", "-")[-12:]
    candidate = base_slug[:120]
    index = 1
    while True:
        existing = await session.scalar(
            select(Organization).where(Organization.slug == candidate)
        )
        if (
            existing is None
            or existing.workos_organization_id == workos_organization_id
        ):
            return candidate
        index += 1
        suffix_text = f"-{suffix}" if index == 2 else f"-{suffix}-{index}"
        candidate = f"{base_slug[: 120 - len(suffix_text)]}{suffix_text}"


@router.post(
    "/workspace",
    response_model=WorkspaceSyncResponse,
    summary="Synchronize an onboarded WorkOS workspace",
)
async def sync_onboarded_workspace(
    payload: WorkspaceSyncRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> WorkspaceSyncResponse:
    if (
        context.principal.organization_id is not None
        and context.principal.organization_id != payload.workos_organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Authenticated session already has a different active organization",
        )

    organization = await session.scalar(
        select(Organization).where(
            Organization.workos_organization_id == payload.workos_organization_id
        )
    )

    if organization is None:
        base_slug = slugify_organization_name(payload.organization_name)
        organization = Organization(
            name=payload.organization_name,
            slug=await unique_organization_slug(
                session,
                base_slug,
                payload.workos_organization_id,
            ),
            workos_organization_id=payload.workos_organization_id,
            owner_user_id=context.user.id,
        )
        session.add(organization)
        await session.flush()
    else:
        organization.name = payload.organization_name
        organization.owner_user_id = context.user.id

    membership = await session.scalar(
        select(OrganizationMembership)
        .where(OrganizationMembership.organization_id == organization.id)
        .where(OrganizationMembership.user_id == context.user.id)
    )

    if membership is None:
        membership = OrganizationMembership(
            organization_id=organization.id,
            user_id=context.user.id,
            role=MembershipRole.owner,
            workos_membership_id=payload.workos_membership_id,
            status=payload.membership_status,
        )
        session.add(membership)
    else:
        membership.role = MembershipRole.owner
        membership.workos_membership_id = (
            payload.workos_membership_id or membership.workos_membership_id
        )
        membership.status = payload.membership_status

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace onboarding records conflict with existing local data",
        ) from exc

    return WorkspaceSyncResponse(
        organization_id=str(organization.id),
        organization_slug=organization.slug,
        membership_role=MembershipRole.owner,
    )
