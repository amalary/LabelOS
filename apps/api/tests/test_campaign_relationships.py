import asyncio
from collections.abc import Iterator

import pytest
from labelos_database.base import Base
from labelos_database.models import (
    Artist,
    Campaign,
    CampaignArtist,
    CampaignMember,
    CampaignRelease,
    Organization,
    Release,
    UniversalProfile,
    User,
    WorkspaceMembership,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.repositories.campaign_relationships import (
    add_campaign_artist,
    add_campaign_member,
    add_campaign_release,
    list_campaign_artists,
    list_campaign_members,
    list_campaign_releases,
    remove_campaign_artist,
    remove_campaign_member,
    remove_campaign_release,
)


@pytest.fixture
def sessionmaker() -> Iterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())
    yield async_sessionmaker(bind=engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


async def _seed_campaign_graph(session: AsyncSession) -> dict[str, object]:
    organization = Organization(
        name="Alpha Label",
        slug="alpha-campaign-relationships",
        owner=User(email="owner-alpha@example.com"),
    )
    other_organization = Organization(
        name="Beta Label",
        slug="beta-campaign-relationships",
        owner=User(email="owner-beta@example.com"),
    )
    profile = UniversalProfile(
        user=User(email="member-alpha@example.com"),
        slug="member-alpha",
    )
    other_profile = UniversalProfile(
        user=User(email="member-beta@example.com"),
        slug="member-beta",
    )
    workspace_membership = WorkspaceMembership(
        workspace=organization,
        profile=profile,
    )
    other_workspace_membership = WorkspaceMembership(
        workspace=other_organization,
        profile=other_profile,
    )
    artist = Artist(name="Primary Artist", organization=organization)
    collaborator = Artist(name="Featured Artist", organization=organization)
    other_artist = Artist(name="Outside Artist", organization=other_organization)
    release = Release(title="Lead Single", organization=organization, artist=artist)
    follow_up_release = Release(
        title="Remix Pack",
        organization=organization,
        artist=artist,
    )
    other_release = Release(
        title="Outside Single",
        organization=other_organization,
        artist=other_artist,
    )
    campaign = Campaign(
        name="Launch Campaign",
        organization=organization,
        primary_artist=artist,
        release=release,
    )
    other_campaign = Campaign(
        name="Outside Campaign",
        organization=other_organization,
        primary_artist=other_artist,
        release=other_release,
    )
    session.add_all(
        [
            campaign,
            other_campaign,
            workspace_membership,
            other_workspace_membership,
            collaborator,
            follow_up_release,
        ]
    )
    await session.flush()
    return {
        "organization": organization,
        "other_organization": other_organization,
        "campaign": campaign,
        "other_campaign": other_campaign,
        "workspace_membership": workspace_membership,
        "other_workspace_membership": other_workspace_membership,
        "artist": artist,
        "collaborator": collaborator,
        "other_artist": other_artist,
        "release": release,
        "follow_up_release": follow_up_release,
        "other_release": other_release,
    }


def test_campaign_member_helpers_manage_workspace_participants(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[int, list[str], bool, int]:
        async with sessionmaker() as session:
            data = await _seed_campaign_graph(session)
            organization = data["organization"]
            campaign = data["campaign"]
            workspace_membership = data["workspace_membership"]
            other_workspace_membership = data["other_workspace_membership"]

            assert isinstance(organization, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(workspace_membership, WorkspaceMembership)
            assert isinstance(other_workspace_membership, WorkspaceMembership)

            link = await add_campaign_member(
                session,
                organization.id,
                campaign.id,
                workspace_membership.id,
            )
            duplicate = await add_campaign_member(
                session,
                organization.id,
                campaign.id,
                workspace_membership.id,
                participation_status="confirmed",
            )
            outside = await add_campaign_member(
                session,
                organization.id,
                campaign.id,
                other_workspace_membership.id,
            )
            members = await list_campaign_members(session, organization.id, campaign.id)
            removed = await remove_campaign_member(
                session,
                organization.id,
                campaign.id,
                workspace_membership.id,
            )
            remaining = await session.scalar(
                select(func.count()).select_from(CampaignMember)
            )
            await session.commit()

            assert link is not None
            assert duplicate is link
            assert outside is None
            assert members is not None
            return (
                len(members),
                [member.participation_status for member in members],
                removed,
                remaining or 0,
            )

    count, statuses, removed, remaining = asyncio.run(run())

    assert count == 1
    assert statuses == ["confirmed"]
    assert removed is True
    assert remaining == 0


def test_campaign_artist_helpers_support_primary_and_collaborator_links(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[list[tuple[str, str]], bool, int]:
        async with sessionmaker() as session:
            data = await _seed_campaign_graph(session)
            organization = data["organization"]
            campaign = data["campaign"]
            artist = data["artist"]
            collaborator = data["collaborator"]
            other_artist = data["other_artist"]

            assert isinstance(organization, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(artist, Artist)
            assert isinstance(collaborator, Artist)
            assert isinstance(other_artist, Artist)

            primary = await add_campaign_artist(
                session,
                organization.id,
                campaign.id,
                artist.id,
                relationship_kind="primary",
            )
            duplicate = await add_campaign_artist(
                session,
                organization.id,
                campaign.id,
                artist.id,
                relationship_kind="lead",
            )
            featured = await add_campaign_artist(
                session,
                organization.id,
                campaign.id,
                collaborator.id,
                relationship_kind="featured",
                sort_order=1,
            )
            outside = await add_campaign_artist(
                session,
                organization.id,
                campaign.id,
                other_artist.id,
            )
            artists = await list_campaign_artists(session, organization.id, campaign.id)
            removed = await remove_campaign_artist(
                session,
                organization.id,
                campaign.id,
                collaborator.id,
            )
            remaining = await session.scalar(
                select(func.count()).select_from(CampaignArtist)
            )
            await session.commit()

            assert primary is not None
            assert duplicate is primary
            assert featured is not None
            assert outside is None
            assert artists is not None
            return (
                [(link.artist.name, link.relationship_kind) for link in artists],
                removed,
                remaining or 0,
            )

    artists, removed, remaining = asyncio.run(run())

    assert artists == [
        ("Primary Artist", "lead"),
        ("Featured Artist", "featured"),
    ]
    assert removed is True
    assert remaining == 1


def test_campaign_release_helpers_support_multiple_release_links(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[list[tuple[str, str]], bool, int]:
        async with sessionmaker() as session:
            data = await _seed_campaign_graph(session)
            organization = data["organization"]
            campaign = data["campaign"]
            release = data["release"]
            follow_up_release = data["follow_up_release"]
            other_release = data["other_release"]

            assert isinstance(organization, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(release, Release)
            assert isinstance(follow_up_release, Release)
            assert isinstance(other_release, Release)

            primary = await add_campaign_release(
                session,
                organization.id,
                campaign.id,
                release.id,
                relationship_kind="primary",
            )
            duplicate = await add_campaign_release(
                session,
                organization.id,
                campaign.id,
                release.id,
                relationship_kind="focus",
            )
            follow_up = await add_campaign_release(
                session,
                organization.id,
                campaign.id,
                follow_up_release.id,
                relationship_kind="follow_up",
            )
            outside = await add_campaign_release(
                session,
                organization.id,
                campaign.id,
                other_release.id,
            )
            releases = await list_campaign_releases(
                session,
                organization.id,
                campaign.id,
            )
            removed = await remove_campaign_release(
                session,
                organization.id,
                campaign.id,
                follow_up_release.id,
            )
            remaining = await session.scalar(
                select(func.count()).select_from(CampaignRelease)
            )
            await session.commit()

            assert primary is not None
            assert duplicate is primary
            assert follow_up is not None
            assert outside is None
            assert releases is not None
            return (
                [(link.release.title, link.relationship_kind) for link in releases],
                removed,
                remaining or 0,
            )

    releases, removed, remaining = asyncio.run(run())

    assert releases == [
        ("Lead Single", "focus"),
        ("Remix Pack", "follow_up"),
    ]
    assert removed is True
    assert remaining == 1
