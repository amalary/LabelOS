import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from labelos_database.base import Base
from labelos_database.capabilities import Capability
from labelos_database.models import (
    Artist,
    Campaign,
    MarketingContentItem,
    MarketingContentItemStatus,
    MembershipRole,
    Organization,
    OrganizationMembership,
    Release,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspacePermission,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.services.marketing_content_service import (
    MarketingContentAuthorizationError,
    MarketingContentChannelCreate,
    MarketingContentChannelUpdate,
    MarketingContentItemCreate,
    MarketingContentItemQuery,
    MarketingContentItemUpdate,
    MarketingContentLifecycleError,
    MarketingContentNotFoundError,
    MarketingContentRelationshipError,
    archive_content_item,
    create_content_item,
    get_campaign_content_item,
    get_content_item,
    list_campaign_content_items,
    list_content_items,
    list_content_items_by_date_range,
    replace_channels,
    transition_status,
    update_channel,
    update_content_item,
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


async def _seed_workspace_graph(session: AsyncSession) -> dict[str, object]:
    workspace = Organization(
        name="Alpha Label",
        slug="alpha-marketing-content",
        owner=User(email="owner-alpha-content@example.com"),
    )
    other_workspace = Organization(
        name="Beta Label",
        slug="beta-marketing-content",
        owner=User(email="owner-beta-content@example.com"),
    )
    creator_profile = UniversalProfile(
        user=User(email="creator-alpha-content@example.com"),
        slug="creator-alpha-content",
    )
    owner_profile = UniversalProfile(
        user=User(email="lead-alpha-content@example.com"),
        slug="lead-alpha-content",
    )
    approver_profile = UniversalProfile(
        user=User(email="approver-alpha-content@example.com"),
        slug="approver-alpha-content",
    )
    other_profile = UniversalProfile(
        user=User(email="lead-beta-content@example.com"),
        slug="lead-beta-content",
    )
    workspace_membership = WorkspaceMembership(
        workspace=workspace,
        profile=creator_profile,
    )
    owner_membership = WorkspaceMembership(
        workspace=workspace,
        profile=owner_profile,
    )
    approver_membership = WorkspaceMembership(
        workspace=workspace,
        profile=approver_profile,
    )
    other_membership = WorkspaceMembership(
        workspace=other_workspace,
        profile=other_profile,
    )
    artist = Artist(name="Alpha Artist", organization=workspace)
    other_artist = Artist(name="Beta Artist", organization=other_workspace)
    release = Release(title="Alpha Release", organization=workspace, artist=artist)
    alternate_release = Release(title="Alpha Side B", organization=workspace)
    other_release = Release(
        title="Beta Release",
        organization=other_workspace,
        artist=other_artist,
    )
    campaign = Campaign(
        name="Alpha Campaign",
        organization=workspace,
        primary_artist=artist,
        release=release,
    )
    other_campaign = Campaign(
        name="Beta Campaign",
        organization=other_workspace,
        primary_artist=other_artist,
        release=other_release,
    )
    session.add_all(
        [
            workspace_membership,
            owner_membership,
            approver_membership,
            other_membership,
            release,
            alternate_release,
            campaign,
            other_campaign,
        ]
    )
    await session.flush()
    return {
        "workspace": workspace,
        "other_workspace": other_workspace,
        "creator_profile": creator_profile,
        "owner_profile": owner_profile,
        "approver_profile": approver_profile,
        "other_profile": other_profile,
        "artist": artist,
        "other_artist": other_artist,
        "release": release,
        "alternate_release": alternate_release,
        "other_release": other_release,
        "campaign": campaign,
        "other_campaign": other_campaign,
    }


async def _seed_authorized_actor(
    session: AsyncSession,
    *,
    workspace: Organization,
    email: str,
    capability_keys: list[str],
    department_access: list[str] | None = None,
) -> User:
    user = User(email=email)
    profile = UniversalProfile(user=user, slug=email.split("@", maxsplit=1)[0])
    membership = OrganizationMembership(
        organization=workspace,
        user=user,
        role=MembershipRole.guest,
        workspace_permission=WorkspacePermission.guest,
        department_access=department_access or ["marketing"],
        capability_permissions=capability_keys,
    )
    workspace_membership = WorkspaceMembership(
        workspace=workspace,
        profile=profile,
        organization_membership=membership,
        status="active",
    )
    session.add_all([user, profile, membership, workspace_membership])
    await session.flush()
    return user


def test_marketing_content_service_authorizes_content_actions_by_capability(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            other_workspace = data["other_workspace"]
            campaign = data["campaign"]
            other_campaign = data["other_campaign"]
            approver_profile = data["approver_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(other_workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(other_campaign, Campaign)
            assert isinstance(approver_profile, UniversalProfile)

            item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Capability Scoped",
                    content_type="image",
                ),
            )
            other_item = await create_content_item(
                session,
                other_workspace.id,
                MarketingContentItemCreate(
                    campaign_id=other_campaign.id,
                    title="Other Workspace",
                    content_type="image",
                ),
            )
            actors = {
                "view": await _seed_authorized_actor(
                    session,
                    workspace=workspace,
                    email="content-view@example.com",
                    capability_keys=[Capability.marketing_content_view.value],
                ),
                "create": await _seed_authorized_actor(
                    session,
                    workspace=workspace,
                    email="content-create@example.com",
                    capability_keys=[Capability.marketing_content_create.value],
                ),
                "edit": await _seed_authorized_actor(
                    session,
                    workspace=workspace,
                    email="content-edit@example.com",
                    capability_keys=[Capability.marketing_content_edit.value],
                ),
                "archive": await _seed_authorized_actor(
                    session,
                    workspace=workspace,
                    email="content-archive@example.com",
                    capability_keys=[Capability.marketing_content_archive.value],
                ),
                "submit": await _seed_authorized_actor(
                    session,
                    workspace=workspace,
                    email="content-submit@example.com",
                    capability_keys=[
                        Capability.marketing_content_submit_for_review.value
                    ],
                ),
                "approve": await _seed_authorized_actor(
                    session,
                    workspace=workspace,
                    email="content-approve@example.com",
                    capability_keys=[Capability.marketing_content_approve.value],
                ),
                "none": await _seed_authorized_actor(
                    session,
                    workspace=workspace,
                    email="content-none@example.com",
                    capability_keys=[],
                ),
                "campaign_view": await _seed_authorized_actor(
                    session,
                    workspace=workspace,
                    email="campaign-view-only@example.com",
                    capability_keys=[Capability.marketing_campaign_view.value],
                ),
            }

            result: dict[str, bool] = {}
            result["allowed_view"] = (
                await get_content_item(
                    session,
                    workspace.id,
                    item.id,
                    actor=actors["view"].id,
                )
            ).id == item.id
            try:
                await get_content_item(
                    session,
                    workspace.id,
                    item.id,
                    actor=actors["none"].id,
                )
            except MarketingContentAuthorizationError:
                result["denied_view"] = True

            created = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Created With Capability",
                    content_type="image",
                ),
                actor=actors["create"].id,
            )
            result["allowed_create"] = created.title == "Created With Capability"
            try:
                await create_content_item(
                    session,
                    workspace.id,
                    MarketingContentItemCreate(
                        campaign_id=campaign.id,
                        title="Denied Create",
                        content_type="image",
                    ),
                    actor=actors["none"].id,
                )
            except MarketingContentAuthorizationError:
                result["denied_create"] = True

            edited = await update_content_item(
                session,
                workspace.id,
                item.id,
                MarketingContentItemUpdate(title="Edited With Capability"),
                actor=actors["edit"].id,
            )
            result["allowed_edit"] = edited.title == "Edited With Capability"
            try:
                await update_content_item(
                    session,
                    workspace.id,
                    item.id,
                    MarketingContentItemUpdate(title="Denied Edit"),
                    actor=actors["none"].id,
                )
            except MarketingContentAuthorizationError:
                result["denied_edit"] = True

            submit_item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Submit",
                    content_type="image",
                ),
            )
            submitted = await transition_status(
                session,
                workspace.id,
                submit_item.id,
                MarketingContentItemStatus.in_review,
                actor=actors["submit"].id,
            )
            result["allowed_submit_for_review"] = (
                submitted.status == MarketingContentItemStatus.in_review
            )
            try:
                await transition_status(
                    session,
                    workspace.id,
                    item.id,
                    MarketingContentItemStatus.in_review,
                    actor=actors["none"].id,
                )
            except MarketingContentAuthorizationError:
                result["denied_submit_for_review"] = True

            approve_item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Approve",
                    content_type="image",
                ),
            )
            approved = await transition_status(
                session,
                workspace.id,
                approve_item.id,
                MarketingContentItemStatus.approved,
                actor=actors["approve"].id,
                approved_by_profile_id=approver_profile.id,
            )
            result["allowed_approval"] = (
                approved.status == MarketingContentItemStatus.approved
            )
            try:
                await transition_status(
                    session,
                    workspace.id,
                    item.id,
                    MarketingContentItemStatus.approved,
                    actor=actors["none"].id,
                    approved_by_profile_id=approver_profile.id,
                )
            except MarketingContentAuthorizationError:
                result["denied_approval"] = True
            try:
                await transition_status(
                    session,
                    workspace.id,
                    item.id,
                    MarketingContentItemStatus.approved,
                    actor=actors["edit"].id,
                    approved_by_profile_id=approver_profile.id,
                )
            except MarketingContentAuthorizationError:
                result["edit_without_approval_denied"] = True

            archive_item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Archive",
                    content_type="image",
                ),
            )
            archived = await archive_content_item(
                session,
                workspace.id,
                archive_item.id,
                actor=actors["archive"].id,
            )
            result["allowed_archive"] = (
                archived.status == MarketingContentItemStatus.archived
            )
            try:
                await archive_content_item(
                    session,
                    workspace.id,
                    item.id,
                    actor=actors["none"].id,
                )
            except MarketingContentAuthorizationError:
                result["denied_archive"] = True

            try:
                await get_content_item(
                    session,
                    other_workspace.id,
                    other_item.id,
                    actor=actors["view"].id,
                )
            except MarketingContentAuthorizationError:
                result["cross_workspace_denial"] = True
            try:
                await get_content_item(
                    session,
                    workspace.id,
                    item.id,
                    actor=actors["campaign_view"].id,
                )
            except MarketingContentAuthorizationError:
                result["unrelated_capability_denied"] = True

            return result

    assert asyncio.run(run()) == {
        "allowed_view": True,
        "denied_view": True,
        "allowed_create": True,
        "denied_create": True,
        "allowed_edit": True,
        "denied_edit": True,
        "allowed_submit_for_review": True,
        "denied_submit_for_review": True,
        "allowed_approval": True,
        "denied_approval": True,
        "edit_without_approval_denied": True,
        "allowed_archive": True,
        "denied_archive": True,
        "cross_workspace_denial": True,
        "unrelated_capability_denied": True,
    }


def test_marketing_content_service_creates_gets_updates_and_lists_items(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[str, str, str, int, list[str], list[str], int, int]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            artist = data["artist"]
            release = data["release"]
            creator_profile = data["creator_profile"]
            owner_profile = data["owner_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(artist, Artist)
            assert isinstance(release, Release)
            assert isinstance(creator_profile, UniversalProfile)
            assert isinstance(owner_profile, UniversalProfile)

            created = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Launch Reel",
                    content_type="Video",
                    artist_id=artist.id,
                    release_id=release.id,
                    copy_text="Initial caption",
                    created_by_user_id=creator_profile.user_id,
                    created_by_profile_id=creator_profile.id,
                    owner_profile_id=owner_profile.id,
                    channels=[
                        MarketingContentChannelCreate(
                            channel="Instagram",
                            placement="Reel",
                        ),
                        MarketingContentChannelCreate(channel="TikTok"),
                    ],
                ),
            )
            loaded = await get_content_item(session, workspace.id, created.id)
            loaded_title = loaded.title
            loaded_channel_count = len(loaded.channels)
            loaded_channel_names = [channel.channel for channel in loaded.channels]
            campaign_loaded = await get_campaign_content_item(
                session,
                workspace.id,
                campaign.id,
                created.id,
            )
            campaign_loaded_title = campaign_loaded.title
            updated = await update_content_item(
                session,
                workspace.id,
                created.id,
                MarketingContentItemUpdate(
                    title="Launch Reel Final",
                    content_type="Short Form",
                    owner_profile_id=creator_profile.id,
                ),
            )
            workspace_page = await list_content_items(session, workspace.id)
            campaign_page = await list_campaign_content_items(
                session,
                workspace.id,
                campaign.id,
            )

            return (
                loaded_title,
                campaign_loaded_title,
                updated.content_type,
                loaded_channel_count,
                loaded_channel_names,
                [item.title for item in campaign_page.items],
                workspace_page.total,
                campaign_page.total,
            )

    result = asyncio.run(run())

    assert result == (
        "Launch Reel",
        "Launch Reel",
        "short form",
        2,
        ["instagram", "tiktok"],
        ["Launch Reel Final"],
        1,
        1,
    )


def test_marketing_content_service_replaces_and_updates_channels(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[list[tuple[str, str]], str, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)

            item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Carousel",
                    content_type="image",
                    channels=[MarketingContentChannelCreate(channel="instagram")],
                ),
            )
            replaced = await replace_channels(
                session,
                workspace.id,
                item.id,
                [
                    MarketingContentChannelCreate(
                        channel="Instagram",
                        placement="Feed",
                    ),
                    MarketingContentChannelCreate(channel="Threads"),
                ],
            )
            updated_channel = await update_channel(
                session,
                workspace.id,
                item.id,
                replaced.channels[0].id,
                MarketingContentChannelUpdate(
                    placement="Story",
                    copy_text_override="Story cut",
                ),
            )
            duplicate_rejected = False
            try:
                await replace_channels(
                    session,
                    workspace.id,
                    item.id,
                    [
                        MarketingContentChannelCreate(channel="instagram"),
                        MarketingContentChannelCreate(
                            channel="Instagram",
                            placement="default",
                        ),
                    ],
                )
            except MarketingContentRelationshipError:
                duplicate_rejected = True
            reloaded = await get_content_item(session, workspace.id, item.id)
            return (
                [(channel.channel, channel.placement) for channel in reloaded.channels],
                updated_channel.copy_text_override or "",
                duplicate_rejected,
            )

    targets, override, duplicate_rejected = asyncio.run(run())

    assert targets == [("instagram", "story"), ("threads", "default")]
    assert override == "Story cut"
    assert duplicate_rejected is True


def test_marketing_content_service_filters_items(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[int, int, int, int, int, int, int]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            artist = data["artist"]
            release = data["release"]
            owner_profile = data["owner_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(artist, Artist)
            assert isinstance(release, Release)
            assert isinstance(owner_profile, UniversalProfile)
            scheduled_at = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

            first = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Filtered",
                    content_type="video",
                    artist_id=artist.id,
                    release_id=release.id,
                    owner_profile_id=owner_profile.id,
                    scheduled_at=scheduled_at,
                    channels=[MarketingContentChannelCreate(channel="instagram")],
                ),
            )
            await transition_status(
                session,
                workspace.id,
                first.id,
                "in_review",
            )
            await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Unfiltered",
                    content_type="image",
                    scheduled_at=scheduled_at + timedelta(days=20),
                    channels=[MarketingContentChannelCreate(channel="tiktok")],
                ),
            )

            campaign_page = await list_content_items(
                session,
                workspace.id,
                query=MarketingContentItemQuery(campaign_id=campaign.id),
            )
            artist_page = await list_content_items(
                session,
                workspace.id,
                query=MarketingContentItemQuery(artist_id=artist.id),
            )
            release_page = await list_content_items(
                session,
                workspace.id,
                query=MarketingContentItemQuery(release_id=release.id),
            )
            status_page = await list_content_items(
                session,
                workspace.id,
                query=MarketingContentItemQuery(status="in_review"),
            )
            channel_page = await list_content_items(
                session,
                workspace.id,
                query=MarketingContentItemQuery(channel="Instagram"),
            )
            owner_page = await list_content_items(
                session,
                workspace.id,
                query=MarketingContentItemQuery(owner_profile_id=owner_profile.id),
            )
            type_page = await list_content_items(
                session,
                workspace.id,
                query=MarketingContentItemQuery(content_type="Video"),
            )
            date_page = await list_content_items_by_date_range(
                session,
                workspace.id,
                scheduled_start=scheduled_at - timedelta(days=1),
                scheduled_end=scheduled_at + timedelta(days=1),
            )
            return (
                campaign_page.total,
                artist_page.total,
                release_page.total,
                status_page.total,
                channel_page.total,
                owner_page.total,
                type_page.total + date_page.total,
            )

    result = asyncio.run(run())

    assert result == (2, 1, 1, 1, 1, 1, 2)


def test_marketing_content_service_enforces_workspace_and_relationship_validation(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, bool, bool, bool, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            other_workspace = data["other_workspace"]
            campaign = data["campaign"]
            other_campaign = data["other_campaign"]
            other_artist = data["other_artist"]
            other_release = data["other_release"]
            other_profile = data["other_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(other_workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(other_campaign, Campaign)
            assert isinstance(other_artist, Artist)
            assert isinstance(other_release, Release)
            assert isinstance(other_profile, UniversalProfile)

            item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Scoped",
                    content_type="image",
                ),
            )
            isolated_get = False
            cross_campaign = False
            invalid_artist = False
            invalid_release = False
            invalid_owner = False
            try:
                await get_content_item(session, other_workspace.id, item.id)
            except MarketingContentNotFoundError:
                isolated_get = True
            try:
                await create_content_item(
                    session,
                    workspace.id,
                    MarketingContentItemCreate(
                        campaign_id=other_campaign.id,
                        title="Cross Campaign",
                        content_type="image",
                    ),
                )
            except MarketingContentNotFoundError:
                cross_campaign = True
            try:
                await update_content_item(
                    session,
                    workspace.id,
                    item.id,
                    MarketingContentItemUpdate(artist_id=other_artist.id),
                )
            except MarketingContentRelationshipError:
                invalid_artist = True
            try:
                await update_content_item(
                    session,
                    workspace.id,
                    item.id,
                    MarketingContentItemUpdate(release_id=other_release.id),
                )
            except MarketingContentRelationshipError:
                invalid_release = True
            try:
                await update_content_item(
                    session,
                    workspace.id,
                    item.id,
                    MarketingContentItemUpdate(owner_profile_id=other_profile.id),
                )
            except MarketingContentRelationshipError:
                invalid_owner = True
            return (
                isolated_get,
                cross_campaign,
                invalid_artist,
                invalid_release,
                invalid_owner,
            )

    assert asyncio.run(run()) == (True, True, True, True, True)


def test_marketing_content_service_validates_release_artist_consistency(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> bool:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            release = data["release"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(release, Release)
            other_local_artist = Artist(
                name="Other Local Artist", organization=workspace
            )
            session.add(other_local_artist)
            await session.flush()
            try:
                await create_content_item(
                    session,
                    workspace.id,
                    MarketingContentItemCreate(
                        campaign_id=campaign.id,
                        title="Mismatch",
                        content_type="image",
                        artist_id=other_local_artist.id,
                        release_id=release.id,
                    ),
                )
            except MarketingContentRelationshipError:
                return True
            return False

    assert asyncio.run(run()) is True


def test_marketing_content_service_validates_all_status_transitions(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    valid_pairs = [
        (MarketingContentItemStatus.draft, MarketingContentItemStatus.in_review),
        (MarketingContentItemStatus.draft, MarketingContentItemStatus.approved),
        (MarketingContentItemStatus.draft, MarketingContentItemStatus.cancelled),
        (MarketingContentItemStatus.draft, MarketingContentItemStatus.archived),
        (MarketingContentItemStatus.in_review, MarketingContentItemStatus.draft),
        (MarketingContentItemStatus.in_review, MarketingContentItemStatus.approved),
        (MarketingContentItemStatus.in_review, MarketingContentItemStatus.cancelled),
        (MarketingContentItemStatus.in_review, MarketingContentItemStatus.archived),
        (MarketingContentItemStatus.approved, MarketingContentItemStatus.draft),
        (MarketingContentItemStatus.approved, MarketingContentItemStatus.scheduled),
        (MarketingContentItemStatus.approved, MarketingContentItemStatus.cancelled),
        (MarketingContentItemStatus.approved, MarketingContentItemStatus.archived),
        (MarketingContentItemStatus.scheduled, MarketingContentItemStatus.approved),
        (MarketingContentItemStatus.scheduled, MarketingContentItemStatus.published),
        (MarketingContentItemStatus.scheduled, MarketingContentItemStatus.cancelled),
        (MarketingContentItemStatus.scheduled, MarketingContentItemStatus.archived),
        (MarketingContentItemStatus.published, MarketingContentItemStatus.archived),
        (MarketingContentItemStatus.cancelled, MarketingContentItemStatus.archived),
    ]

    async def run() -> list[MarketingContentItemStatus]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            approver_profile = data["approver_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(approver_profile, UniversalProfile)
            statuses: list[MarketingContentItemStatus] = []
            for index, (source, target) in enumerate(valid_pairs):
                item = MarketingContentItem(
                    organization_id=workspace.id,
                    campaign_id=campaign.id,
                    title=f"Transition {index}",
                    content_type="image",
                    status=source,
                    scheduled_at=datetime(2026, 9, 10, tzinfo=UTC),
                )
                session.add(item)
                await session.flush()
                transitioned = await transition_status(
                    session,
                    workspace.id,
                    item.id,
                    target,
                    approved_by_profile_id=approver_profile.id,
                    assume_approval_capability=True,
                )
                statuses.append(transitioned.status)
            return statuses

    assert asyncio.run(run()) == [target for _, target in valid_pairs]


def test_marketing_content_service_rejects_invalid_status_transitions(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, bool, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Lifecycle",
                    content_type="image",
                ),
            )
            invalid = False
            invalid_status = False
            approval_required = False
            try:
                await transition_status(session, workspace.id, item.id, "published")
            except MarketingContentLifecycleError:
                invalid = True
            try:
                await transition_status(session, workspace.id, item.id, "unknown")
            except MarketingContentLifecycleError:
                invalid_status = True
            try:
                await transition_status(session, workspace.id, item.id, "approved")
            except MarketingContentAuthorizationError:
                approval_required = True
            return invalid, invalid_status, approval_required

    assert asyncio.run(run()) == (True, True, True)


def test_marketing_content_service_applies_lifecycle_timestamps_and_terminal_archive(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, bool, bool, bool, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            approver_profile = data["approver_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(approver_profile, UniversalProfile)
            item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Timed",
                    content_type="image",
                    scheduled_at=datetime(2026, 9, 10, tzinfo=UTC),
                ),
            )
            in_review = await transition_status(
                session,
                workspace.id,
                item.id,
                "in_review",
            )
            approval_requested = in_review.approval_requested_at is not None
            approved = await transition_status(
                session,
                workspace.id,
                item.id,
                "approved",
                approved_by_profile_id=approver_profile.id,
                assume_approval_capability=True,
            )
            draft = await transition_status(session, workspace.id, item.id, "draft")
            approval_cleared = (
                draft.approved_at is None and draft.approved_by_profile_id is None
            )
            await transition_status(
                session,
                workspace.id,
                item.id,
                "approved",
                approved_by_profile_id=approver_profile.id,
                assume_approval_capability=True,
            )
            await transition_status(session, workspace.id, item.id, "scheduled")
            published = await transition_status(
                session, workspace.id, item.id, "published"
            )
            archived = await archive_content_item(session, workspace.id, item.id)
            terminal = False
            try:
                await transition_status(session, workspace.id, item.id, "draft")
            except MarketingContentLifecycleError:
                terminal = True
            return (
                approval_requested,
                approved.approved_at is not None
                and approved.approved_by_profile_id == approver_profile.id,
                approval_cleared,
                published.published_at is not None,
                archived.status == MarketingContentItemStatus.archived and terminal,
            )

    assert asyncio.run(run()) == (True, True, True, True, True)


def test_marketing_content_service_clears_approval_on_material_content_change(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[MarketingContentItemStatus, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            approver_profile = data["approver_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(approver_profile, UniversalProfile)
            item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Approved",
                    content_type="image",
                ),
            )
            approved = await transition_status(
                session,
                workspace.id,
                item.id,
                "approved",
                approved_by_profile_id=approver_profile.id,
                assume_approval_capability=True,
            )
            assert approved.approved_at is not None
            changed = await update_content_item(
                session,
                workspace.id,
                item.id,
                MarketingContentItemUpdate(
                    title="Approved Edited",
                    material_change=True,
                ),
            )
            return changed.status, changed.approved_at is None

    assert asyncio.run(run()) == (MarketingContentItemStatus.draft, True)


def test_marketing_content_service_validates_scheduled_transition(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, MarketingContentItemStatus]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            approver_profile = data["approver_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(approver_profile, UniversalProfile)
            item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Needs Schedule",
                    content_type="image",
                ),
            )
            await transition_status(
                session,
                workspace.id,
                item.id,
                "approved",
                approved_by_profile_id=approver_profile.id,
                assume_approval_capability=True,
            )
            rejected = False
            try:
                await transition_status(session, workspace.id, item.id, "scheduled")
            except MarketingContentLifecycleError:
                rejected = True
            await update_content_item(
                session,
                workspace.id,
                item.id,
                MarketingContentItemUpdate(
                    scheduled_at=datetime(2026, 9, 10, tzinfo=UTC)
                ),
            )
            await transition_status(
                session,
                workspace.id,
                item.id,
                "approved",
                approved_by_profile_id=approver_profile.id,
                assume_approval_capability=True,
            )
            scheduled = await transition_status(
                session,
                workspace.id,
                item.id,
                "scheduled",
            )
            return rejected, scheduled.status

    assert asyncio.run(run()) == (True, MarketingContentItemStatus.scheduled)


def test_marketing_content_service_rejects_missing_created_user_membership(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> bool:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            try:
                await create_content_item(
                    session,
                    workspace.id,
                    MarketingContentItemCreate(
                        campaign_id=campaign.id,
                        title="Missing User",
                        content_type="image",
                        created_by_user_id=uuid4(),
                    ),
                )
            except MarketingContentRelationshipError:
                return True
            return False

    assert asyncio.run(run()) is True
