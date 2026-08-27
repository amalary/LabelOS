from uuid import UUID

from labelos_database.models import (
    Artist,
    Campaign,
    CampaignArtist,
    CampaignMember,
    CampaignRelease,
    Release,
    WorkspaceMembership,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _campaign_in_organization(
    session: AsyncSession,
    organization_id: UUID,
    campaign_id: UUID,
) -> Campaign | None:
    return await session.scalar(
        select(Campaign)
        .where(Campaign.organization_id == organization_id)
        .where(Campaign.id == campaign_id)
    )


async def add_campaign_member(
    session: AsyncSession,
    organization_id: UUID,
    campaign_id: UUID,
    workspace_membership_id: UUID,
    *,
    participation_status: str = "active",
    responsibility_label: str | None = None,
) -> CampaignMember | None:
    campaign = await _campaign_in_organization(session, organization_id, campaign_id)
    workspace_membership = await session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == organization_id)
        .where(WorkspaceMembership.id == workspace_membership_id)
        .where(WorkspaceMembership.status == "active")
    )
    if campaign is None or workspace_membership is None:
        return None

    existing = await session.get(
        CampaignMember,
        {
            "campaign_id": campaign_id,
            "workspace_membership_id": workspace_membership_id,
        },
    )
    if existing is not None:
        existing.participation_status = participation_status
        existing.responsibility_label = responsibility_label
        await session.flush()
        return existing

    link = CampaignMember(
        campaign_id=campaign_id,
        workspace_membership_id=workspace_membership_id,
        participation_status=participation_status,
        responsibility_label=responsibility_label,
    )
    session.add(link)
    await session.flush()
    return link


async def get_campaign_member(
    session: AsyncSession,
    organization_id: UUID,
    campaign_id: UUID,
    workspace_membership_id: UUID,
) -> CampaignMember | None:
    campaign = await _campaign_in_organization(session, organization_id, campaign_id)
    if campaign is None:
        return None

    return await session.scalar(
        select(CampaignMember)
        .options(
            selectinload(CampaignMember.workspace_membership).selectinload(
                WorkspaceMembership.profile
            )
        )
        .join(WorkspaceMembership)
        .where(CampaignMember.campaign_id == campaign_id)
        .where(CampaignMember.workspace_membership_id == workspace_membership_id)
        .where(WorkspaceMembership.workspace_id == organization_id)
    )


async def list_campaign_members(
    session: AsyncSession,
    organization_id: UUID,
    campaign_id: UUID,
) -> list[CampaignMember] | None:
    campaign = await _campaign_in_organization(session, organization_id, campaign_id)
    if campaign is None:
        return None

    rows = await session.scalars(
        select(CampaignMember)
        .options(
            selectinload(CampaignMember.workspace_membership).selectinload(
                WorkspaceMembership.profile
            )
        )
        .join(WorkspaceMembership)
        .where(CampaignMember.campaign_id == campaign_id)
        .where(WorkspaceMembership.workspace_id == organization_id)
        .order_by(CampaignMember.created_at, CampaignMember.workspace_membership_id)
    )
    return list(rows.all())


async def remove_campaign_member(
    session: AsyncSession,
    organization_id: UUID,
    campaign_id: UUID,
    workspace_membership_id: UUID,
) -> bool:
    campaign = await _campaign_in_organization(session, organization_id, campaign_id)
    if campaign is None:
        return False

    result = await session.execute(
        delete(CampaignMember)
        .where(CampaignMember.campaign_id == campaign_id)
        .where(CampaignMember.workspace_membership_id == workspace_membership_id)
        .where(
            CampaignMember.workspace_membership_id.in_(
                select(WorkspaceMembership.id).where(
                    WorkspaceMembership.workspace_id == organization_id
                )
            )
        )
    )
    await session.flush()
    return (result.rowcount or 0) > 0


async def add_campaign_artist(
    session: AsyncSession,
    organization_id: UUID,
    campaign_id: UUID,
    artist_id: UUID,
    *,
    relationship_kind: str = "collaborator",
    sort_order: int = 0,
) -> CampaignArtist | None:
    campaign = await _campaign_in_organization(session, organization_id, campaign_id)
    artist = await session.scalar(
        select(Artist)
        .where(Artist.organization_id == organization_id)
        .where(Artist.id == artist_id)
    )
    if campaign is None or artist is None:
        return None

    existing = await session.get(
        CampaignArtist,
        {"campaign_id": campaign_id, "artist_id": artist_id},
    )
    if existing is not None:
        existing.relationship_kind = relationship_kind
        existing.sort_order = sort_order
        await session.flush()
        return existing

    link = CampaignArtist(
        campaign_id=campaign_id,
        artist_id=artist_id,
        relationship_kind=relationship_kind,
        sort_order=sort_order,
    )
    session.add(link)
    await session.flush()
    return link


async def list_campaign_artists(
    session: AsyncSession,
    organization_id: UUID,
    campaign_id: UUID,
) -> list[CampaignArtist] | None:
    campaign = await _campaign_in_organization(session, organization_id, campaign_id)
    if campaign is None:
        return None

    rows = await session.scalars(
        select(CampaignArtist)
        .options(selectinload(CampaignArtist.artist))
        .join(Artist)
        .where(CampaignArtist.campaign_id == campaign_id)
        .where(Artist.organization_id == organization_id)
        .order_by(CampaignArtist.sort_order, CampaignArtist.created_at)
    )
    return list(rows.all())


async def remove_campaign_artist(
    session: AsyncSession,
    organization_id: UUID,
    campaign_id: UUID,
    artist_id: UUID,
) -> bool:
    campaign = await _campaign_in_organization(session, organization_id, campaign_id)
    if campaign is None:
        return False

    result = await session.execute(
        delete(CampaignArtist)
        .where(CampaignArtist.campaign_id == campaign_id)
        .where(CampaignArtist.artist_id == artist_id)
        .where(
            CampaignArtist.artist_id.in_(
                select(Artist.id).where(Artist.organization_id == organization_id)
            )
        )
    )
    await session.flush()
    return (result.rowcount or 0) > 0


async def add_campaign_release(
    session: AsyncSession,
    organization_id: UUID,
    campaign_id: UUID,
    release_id: UUID,
    *,
    relationship_kind: str = "related",
) -> CampaignRelease | None:
    campaign = await _campaign_in_organization(session, organization_id, campaign_id)
    release = await session.scalar(
        select(Release)
        .where(Release.organization_id == organization_id)
        .where(Release.id == release_id)
    )
    if campaign is None or release is None:
        return None

    existing = await session.get(
        CampaignRelease,
        {"campaign_id": campaign_id, "release_id": release_id},
    )
    if existing is not None:
        existing.relationship_kind = relationship_kind
        await session.flush()
        return existing

    link = CampaignRelease(
        campaign_id=campaign_id,
        release_id=release_id,
        relationship_kind=relationship_kind,
    )
    session.add(link)
    await session.flush()
    return link


async def list_campaign_releases(
    session: AsyncSession,
    organization_id: UUID,
    campaign_id: UUID,
) -> list[CampaignRelease] | None:
    campaign = await _campaign_in_organization(session, organization_id, campaign_id)
    if campaign is None:
        return None

    rows = await session.scalars(
        select(CampaignRelease)
        .options(selectinload(CampaignRelease.release))
        .join(Release)
        .where(CampaignRelease.campaign_id == campaign_id)
        .where(Release.organization_id == organization_id)
        .order_by(Release.title, CampaignRelease.release_id)
    )
    return list(rows.all())


async def remove_campaign_release(
    session: AsyncSession,
    organization_id: UUID,
    campaign_id: UUID,
    release_id: UUID,
) -> bool:
    campaign = await _campaign_in_organization(session, organization_id, campaign_id)
    if campaign is None:
        return False

    result = await session.execute(
        delete(CampaignRelease)
        .where(CampaignRelease.campaign_id == campaign_id)
        .where(CampaignRelease.release_id == release_id)
        .where(
            CampaignRelease.release_id.in_(
                select(Release.id).where(Release.organization_id == organization_id)
            )
        )
    )
    await session.flush()
    return (result.rowcount or 0) > 0
