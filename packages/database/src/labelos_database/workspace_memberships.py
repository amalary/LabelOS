from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_database.models import (
    OrganizationMembership,
    UniversalProfile,
    User,
    WorkspaceMembership,
)


def _joined_at_for_status(status: str) -> datetime | None:
    if status in {"active", "accepted"}:
        return datetime.now(UTC)
    return None


async def get_or_create_profile_for_user(
    session: AsyncSession,
    user: User,
) -> UniversalProfile:
    profile = await session.scalar(
        select(UniversalProfile).where(UniversalProfile.user_id == user.id)
    )
    if profile is not None:
        return profile

    profile = UniversalProfile(
        user_id=user.id,
        display_name=user.display_name,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.profile_image_url,
        primary_email=user.email,
        profile_status="active",
        onboarding_status="not_started",
    )
    session.add(profile)
    await session.flush()
    return profile


async def ensure_workspace_membership_for_organization_membership(
    session: AsyncSession,
    membership: OrganizationMembership,
    *,
    invited_by_profile_id: UUID | None = None,
    joined_at: datetime | None = None,
) -> WorkspaceMembership:
    user = await session.get(User, membership.user_id)
    if user is None:
        raise ValueError("organization membership must reference an existing user")

    profile = await get_or_create_profile_for_user(session, user)
    workspace_membership = await session.scalar(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.organization_membership_id == membership.id,
        )
        .options(selectinload(WorkspaceMembership.organization_membership))
    )
    if workspace_membership is None:
        workspace_membership = await session.scalar(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == membership.organization_id)
            .where(WorkspaceMembership.profile_id == profile.id)
            .options(selectinload(WorkspaceMembership.organization_membership))
        )

    if workspace_membership is None:
        workspace_membership = WorkspaceMembership(
            workspace_id=membership.organization_id,
            profile_id=profile.id,
            organization_membership_id=membership.id,
            status=membership.status,
            invited_by=invited_by_profile_id,
            joined_at=joined_at or _joined_at_for_status(membership.status),
        )
        session.add(workspace_membership)
    else:
        workspace_membership.workspace_id = membership.organization_id
        workspace_membership.profile_id = profile.id
        workspace_membership.organization_membership_id = membership.id
        workspace_membership.status = membership.status
        if workspace_membership.invited_by is None:
            workspace_membership.invited_by = invited_by_profile_id
        if workspace_membership.joined_at is None:
            workspace_membership.joined_at = joined_at or _joined_at_for_status(
                membership.status
            )

    await session.flush()
    return workspace_membership


async def mark_workspace_membership_removed(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    profile_id: UUID,
) -> bool:
    workspace_membership = await session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.profile_id == profile_id)
    )
    if workspace_membership is None:
        return False

    workspace_membership.status = "removed"
    if workspace_membership.organization_membership_id is not None:
        await session.execute(
            delete(OrganizationMembership).where(
                OrganizationMembership.id
                == workspace_membership.organization_membership_id
            )
        )
        workspace_membership.organization_membership_id = None
    await session.flush()
    return True
