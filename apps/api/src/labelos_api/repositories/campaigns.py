from collections.abc import Mapping
from uuid import UUID

from labelos_database.models import (
    Artist,
    Campaign,
    CampaignArtist,
    CampaignMember,
    CampaignRelease,
    Release,
    UniversalProfile,
    WorkspaceMembership,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


def _campaign_load_options():
    return (
        selectinload(Campaign.primary_artist),
        selectinload(Campaign.release),
        selectinload(Campaign.owner_profile),
        selectinload(Campaign.artist_links).selectinload(CampaignArtist.artist),
        selectinload(Campaign.release_links).selectinload(CampaignRelease.release),
        selectinload(Campaign.member_links)
        .selectinload(CampaignMember.workspace_membership)
        .selectinload(WorkspaceMembership.profile),
    )


async def list_campaigns(
    session: AsyncSession,
    workspace_id: UUID,
) -> list[Campaign]:
    rows = await session.scalars(
        select(Campaign)
        .options(*_campaign_load_options())
        .where(Campaign.organization_id == workspace_id)
        .order_by(Campaign.created_at.desc(), Campaign.name)
    )
    return list(rows.all())


async def get_campaign(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
) -> Campaign | None:
    return await session.scalar(
        select(Campaign)
        .options(*_campaign_load_options())
        .where(Campaign.organization_id == workspace_id)
        .where(Campaign.id == campaign_id)
    )


async def create_campaign(
    session: AsyncSession,
    workspace_id: UUID,
    values: Mapping[str, object],
) -> Campaign:
    campaign = Campaign(organization_id=workspace_id, **dict(values))
    session.add(campaign)
    await session.flush()
    return campaign


async def update_campaign(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    values: Mapping[str, object],
) -> Campaign | None:
    campaign = await get_campaign(session, workspace_id, campaign_id)
    if campaign is None:
        return None
    for key, value in values.items():
        setattr(campaign, key, value)
    await session.flush()
    return campaign


async def profile_is_active_workspace_member(
    session: AsyncSession,
    workspace_id: UUID,
    profile_id: UUID,
) -> bool:
    membership_id = await session.scalar(
        select(WorkspaceMembership.id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.profile_id == profile_id)
        .where(WorkspaceMembership.status == "active")
    )
    return membership_id is not None


async def user_is_active_workspace_member(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
) -> bool:
    membership_id = await session.scalar(
        select(WorkspaceMembership.id)
        .join(WorkspaceMembership.profile)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.status == "active")
        .where(UniversalProfile.user_id == user_id)
    )
    return membership_id is not None


async def profile_exists(
    session: AsyncSession,
    profile_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(UniversalProfile.id).where(UniversalProfile.id == profile_id)
        )
        is not None
    )


async def artist_in_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    artist_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(Artist.id)
            .where(Artist.organization_id == workspace_id)
            .where(Artist.id == artist_id)
        )
        is not None
    )


async def release_in_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    release_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(Release.id)
            .where(Release.organization_id == workspace_id)
            .where(Release.id == release_id)
        )
        is not None
    )
