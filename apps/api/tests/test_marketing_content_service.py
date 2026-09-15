import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from labelos_database.base import Base
from labelos_database.capabilities import Capability
from labelos_database.models import (
    ApprovalRequest,
    ApprovalRequestStatus,
    Artist,
    ArtistProfile,
    Campaign,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    MembershipRole,
    Organization,
    OrganizationMembership,
    RealtimeEvent,
    Release,
    SocialAccountConnection,
    SocialAccountConnectionMethod,
    SocialAccountConnectionStatus,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspacePermission,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
)
from labelos_api.services.approval_service import (
    ApprovalDuplicateActiveRequestError,
    approve_request,
    get_approval_history,
    request_changes,
    submit_resource_for_approval,
)
from labelos_api.services.marketing_content_service import (
    ManualPublishScheduleInput,
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
    prepare_assisted_publish_handoff,
    replace_channels,
    transition_status,
    update_channel,
    update_content_item,
    update_content_item_with_channels,
)
from labelos_api.services.social_account_service import (
    DestinationUnavailableReason,
    check_connection_health,
    resolved_destination_for_connection,
)
from labelos_api.social_accounts.providers import (
    SocialAccountConnectionProvider,
    SocialAccountHealth,
    SocialAccountProviderErrorCode,
    SocialAccountProviderKey,
    SocialAccountProviderRegistry,
)


class DegradedInstagramProvider(SocialAccountConnectionProvider):
    provider = SocialAccountProviderKey.instagram
    connection_method = SocialAccountConnectionMethod.direct_api

    def default_capabilities(self) -> tuple[str, ...]:
        return ("content_publish",)

    async def check_connection_health(
        self,
        *,
        credential_ref: str | None,
        token_expires_at=None,
        provider_metadata=None,
    ) -> SocialAccountHealth:
        return SocialAccountHealth(
            healthy=False,
            status="reconnect_required",
            error_code=SocialAccountProviderErrorCode.credential_revoked,
            error_message="Provider authorization was revoked",
        )


async def _submit_and_approve_content(
    session: AsyncSession,
    workspace_id,
    content_item_id,
    approver: User | None = None,
) -> MarketingContentItem:
    submitted = await transition_status(
        session,
        workspace_id,
        content_item_id,
        MarketingContentItemStatus.in_review,
    )
    request = await session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.resource_type == MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
            ApprovalRequest.resource_id == content_item_id,
            ApprovalRequest.resource_revision == submitted.content_revision,
            ApprovalRequest.status == ApprovalRequestStatus.in_review,
        )
    )
    assert request is not None
    if approver is None:
        return await transition_status(
            session,
            workspace_id,
            content_item_id,
            MarketingContentItemStatus.approved,
        )
    await approve_request(session, workspace_id, request.id, actor=approver)
    approved = await session.get(MarketingContentItem, content_item_id)
    assert approved is not None
    return approved


@pytest.fixture
def sessionmaker(database_test_engine) -> Iterator[async_sessionmaker[AsyncSession]]:
    engine = database_test_engine

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())
    yield async_sessionmaker(bind=engine, expire_on_commit=False)


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
    artist_profile = ArtistProfile(
        artist=artist,
        universal_profile=creator_profile,
        stage_name="Alpha Artist",
    )
    other_artist = Artist(name="Beta Artist", organization=other_workspace)
    other_artist_profile = ArtistProfile(
        artist=other_artist,
        universal_profile=other_profile,
        stage_name="Beta Artist",
    )
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
            artist_profile,
            other_artist_profile,
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
        "artist_profile": artist_profile,
        "other_artist": other_artist,
        "other_artist_profile": other_artist_profile,
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
            await transition_status(
                session,
                workspace.id,
                approve_item.id,
                MarketingContentItemStatus.in_review,
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
            except MarketingContentLifecycleError:
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
            except MarketingContentLifecycleError:
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


def test_marketing_content_service_validates_optional_channel_social_account_targets(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            other_workspace = data["other_workspace"]
            campaign = data["campaign"]
            artist = data["artist"]
            artist_profile = data["artist_profile"]
            other_artist_profile = data["other_artist_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(other_workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(artist, Artist)
            assert isinstance(artist_profile, ArtistProfile)
            assert isinstance(other_artist_profile, ArtistProfile)

            unrelated_artist = Artist(name="Other Alpha Artist", organization=workspace)
            unrelated_profile = UniversalProfile(
                user=User(email=f"other-alpha-{uuid4()}@example.com"),
                slug=f"other-alpha-{uuid4()}",
            )
            unrelated_membership = WorkspaceMembership(
                workspace=workspace,
                profile=unrelated_profile,
            )
            unrelated_artist_profile = ArtistProfile(
                artist=unrelated_artist,
                universal_profile=unrelated_profile,
                stage_name="Other Alpha Artist",
            )
            session.add_all([unrelated_membership, unrelated_artist_profile])
            await session.flush()

            automatic = SocialAccountConnection(
                organization=workspace,
                artist_profile=artist_profile,
                provider="instagram",
                username="@alpha",
                connection_method=SocialAccountConnectionMethod.direct_api,
                status=SocialAccountConnectionStatus.connected,
                capabilities=["content_publish"],
            )
            assisted = SocialAccountConnection(
                organization=workspace,
                artist_profile=artist_profile,
                provider="instagram",
                username="@alpha-assisted",
                status=SocialAccountConnectionStatus.connected,
                capabilities=["manual_publish"],
            )
            wrong_provider = SocialAccountConnection(
                organization=workspace,
                artist_profile=artist_profile,
                provider="tiktok",
                username="@alpha-tiktok",
                status=SocialAccountConnectionStatus.connected,
                capabilities=["manual_publish"],
            )
            cross_workspace = SocialAccountConnection(
                organization=other_workspace,
                artist_profile=other_artist_profile,
                provider="instagram",
                username="@beta",
                status=SocialAccountConnectionStatus.connected,
                capabilities=["manual_publish"],
            )
            different_artist = SocialAccountConnection(
                organization=workspace,
                artist_profile=unrelated_artist_profile,
                provider="instagram",
                username="@other-alpha",
                status=SocialAccountConnectionStatus.connected,
                capabilities=["manual_publish"],
            )
            disconnected = SocialAccountConnection(
                organization=workspace,
                artist_profile=artist_profile,
                provider="instagram",
                username="@disconnected",
                status=SocialAccountConnectionStatus.disconnected,
                capabilities=["manual_publish"],
            )
            reconnect_required = SocialAccountConnection(
                organization=workspace,
                artist_profile=artist_profile,
                provider="instagram",
                username="@reconnect",
                status=SocialAccountConnectionStatus.reconnect_required,
                capabilities=["content_publish"],
            )
            missing_capability = SocialAccountConnection(
                organization=workspace,
                artist_profile=artist_profile,
                provider="instagram",
                username="@readonly",
                status=SocialAccountConnectionStatus.connected,
                capabilities=["account_analytics_read"],
            )
            session.add_all(
                [
                    automatic,
                    assisted,
                    wrong_provider,
                    cross_workspace,
                    different_artist,
                    disconnected,
                    reconnect_required,
                    missing_capability,
                ]
            )
            await session.flush()

            no_account = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="No Account",
                    content_type="social_post",
                    channels=[MarketingContentChannelCreate(channel="instagram")],
                ),
            )
            targeted = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Targeted",
                    content_type="social_post",
                    artist_id=artist.id,
                    channels=[
                        MarketingContentChannelCreate(
                            channel="instagram",
                            placement="feed",
                            social_account_connection_id=automatic.id,
                        )
                    ],
                ),
            )
            multiple = await replace_channels(
                session,
                workspace.id,
                targeted.id,
                [
                    MarketingContentChannelCreate(
                        channel="instagram",
                        placement="feed",
                        social_account_connection_id=automatic.id,
                    ),
                    MarketingContentChannelCreate(
                        channel="instagram",
                        placement="story",
                        social_account_connection_id=assisted.id,
                    ),
                ],
            )
            multiple_connection_ids = [
                channel.social_account_connection_id for channel in multiple.channels
            ]
            await replace_channels(
                session,
                workspace.id,
                targeted.id,
                [
                    MarketingContentChannelCreate(
                        channel="instagram",
                        placement="feed",
                        social_account_connection_id=reconnect_required.id,
                    )
                ],
            )

            rejected: dict[str, bool] = {}
            cases = {
                "provider_mismatch": wrong_provider.id,
                "cross_workspace": cross_workspace.id,
                "different_artist": different_artist.id,
                "disconnected": disconnected.id,
                "missing_capability": missing_capability.id,
            }
            for name, connection_id in cases.items():
                try:
                    await create_content_item(
                        session,
                        workspace.id,
                        MarketingContentItemCreate(
                            campaign_id=campaign.id,
                            title=f"Reject {name}",
                            content_type="social_post",
                            artist_id=artist.id,
                            channels=[
                                MarketingContentChannelCreate(
                                    channel="instagram",
                                    social_account_connection_id=connection_id,
                                )
                            ],
                        ),
                    )
                except MarketingContentRelationshipError:
                    rejected[name] = True
            reloaded = await get_content_item(session, workspace.id, targeted.id)
            return {
                "no_account": no_account.channels[0].social_account_connection_id,
                "multiple": multiple_connection_ids,
                "reconnect_required": reloaded.channels[0].social_account_connection_id,
                "rejected": rejected,
            }

    result = asyncio.run(run())

    assert result["no_account"] is None
    assert len(result["multiple"]) == 2
    assert result["reconnect_required"] is not None
    assert result["rejected"] == {
        "provider_mismatch": True,
        "cross_workspace": True,
        "different_artist": True,
        "disconnected": True,
        "missing_capability": True,
    }


def test_draft_post_channel_survives_social_account_reconnect_required_recovery(
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = SocialAccountProviderRegistry([DegradedInstagramProvider()])
    monkeypatch.setattr(
        "labelos_api.social_accounts.providers.provider_registry",
        registry,
    )

    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            artist = data["artist"]
            artist_profile = data["artist_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(artist, Artist)
            assert isinstance(artist_profile, ArtistProfile)

            connection = SocialAccountConnection(
                organization=workspace,
                artist_profile=artist_profile,
                provider="instagram",
                external_account_id="ig-preserved",
                username="@preserved",
                display_name="Preserved Account",
                connection_method=SocialAccountConnectionMethod.direct_api,
                status=SocialAccountConnectionStatus.connected,
                capabilities=["content_publish"],
                credential_ref="memory://credentials/direct",
            )
            session.add(connection)
            await session.flush()

            draft = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Reconnect Integrity Draft",
                    content_type="social_post",
                    artist_id=artist.id,
                    copy_text="Draft copy remains editable.",
                    channels=[
                        MarketingContentChannelCreate(
                            channel="instagram",
                            social_account_connection_id=connection.id,
                            copy_text_override="Channel copy remains intact.",
                        )
                    ],
                ),
            )
            await check_connection_health(
                session,
                workspace.id,
                connection.id,
                provider_registry=registry,
            )
            reloaded = await get_content_item(session, workspace.id, draft.id)
            updated_connection = await session.get(
                SocialAccountConnection,
                connection.id,
            )
            assert updated_connection is not None
            readiness = resolved_destination_for_connection(
                updated_connection,
                workspace_id=workspace.id,
                provider="instagram",
                artist_profile_id=artist_profile.id,
                desired_capability="content_publish",
            )
            return {
                "draft_status": reloaded.status,
                "draft_title": reloaded.title,
                "draft_copy": reloaded.copy_text,
                "channel_fk": reloaded.channels[0].social_account_connection_id,
                "channel_copy": reloaded.channels[0].copy_text_override,
                "connection_status": updated_connection.status,
                "external_account_id": updated_connection.external_account_id,
                "username": updated_connection.username,
                "credential_ref": updated_connection.credential_ref,
                "readiness_usable": readiness.usable,
                "readiness_reasons": readiness.unavailable_reasons,
            }

    result = asyncio.run(run())
    assert result["draft_status"] == MarketingContentItemStatus.draft
    assert result["draft_title"] == "Reconnect Integrity Draft"
    assert result["draft_copy"] == "Draft copy remains editable."
    assert result["channel_fk"] is not None
    assert result["channel_copy"] == "Channel copy remains intact."
    assert (
        result["connection_status"] == SocialAccountConnectionStatus.reconnect_required
    )
    assert result["external_account_id"] == "ig-preserved"
    assert result["username"] == "@preserved"
    assert result["credential_ref"] == "memory://credentials/direct"
    assert result["readiness_usable"] is False
    assert result["readiness_reasons"] == (
        DestinationUnavailableReason.reconnect_required,
    )


def test_prepare_assisted_publish_handoff_returns_scheduler_delivery_contract(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            artist = data["artist"]
            artist_profile = data["artist_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(artist, Artist)
            assert isinstance(artist_profile, ArtistProfile)

            assisted = SocialAccountConnection(
                organization=workspace,
                artist_profile=artist_profile,
                provider="instagram",
                username="@alpha-assisted",
                display_name="Alpha Assisted",
                profile_url="https://instagram.com/alpha-assisted",
                status=SocialAccountConnectionStatus.connected,
                capabilities=["manual_publish", "manual_metrics"],
            )
            session.add(assisted)
            await session.flush()

            item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Manual Reel",
                    content_type="video",
                    artist_id=artist.id,
                    copy_text="Item caption",
                    asset_refs=[{"asset_id": "item_asset"}],
                    metadata_json={"hashtags": ["Alpha", "#Launch"]},
                    channels=[
                        MarketingContentChannelCreate(
                            channel="instagram",
                            placement="reel",
                            social_account_connection_id=assisted.id,
                            copy_text_override="Channel caption",
                            asset_refs=[{"asset_id": "channel_asset"}],
                            metadata_json={"hashtags": ["#Launch", "Reels"]},
                        )
                    ],
                ),
            )
            intended_at = datetime(2026, 9, 15, 17, 30, tzinfo=UTC)
            handoff = await prepare_assisted_publish_handoff(
                session,
                workspace.id,
                item.id,
                item.channels[0].id,
                ManualPublishScheduleInput(intended_publication_at=intended_at),
            )
            return {
                "marketing_content_id": handoff.marketing_content_id,
                "channel_id": handoff.channel_content_item_channel_id,
                "connection_id": handoff.social_account_connection_id,
                "provider": handoff.provider,
                "handle": handoff.handle,
                "account_display": handoff.account_display,
                "capability": handoff.capability,
                "health_status": handoff.health_status,
                "asset_refs": handoff.asset_refs,
                "caption": handoff.caption,
                "hashtags": handoff.hashtags,
                "intended_at": handoff.intended_publication_at,
                "safe_link": handoff.safe_profile_provider_link,
                "instructions": handoff.manual_instructions,
                "completion": handoff.completion,
            }

    result = asyncio.run(run())

    assert result["marketing_content_id"] is not None
    assert result["channel_id"] is not None
    assert result["connection_id"] is not None
    assert result["provider"] == "instagram"
    assert result["handle"] == "@alpha-assisted"
    assert result["account_display"] == "Alpha Assisted"
    assert result["capability"] == "manual_publish"
    assert result["health_status"] == "connected"
    assert result["asset_refs"] == [{"asset_id": "channel_asset"}]
    assert result["caption"] == "Channel caption"
    assert result["hashtags"] == ("#Alpha", "#Launch", "#Reels")
    assert result["intended_at"] == datetime(2026, 9, 15, 17, 30, tzinfo=UTC)
    assert result["safe_link"] == "https://instagram.com/alpha-assisted"
    assert "record the external post ID or URL" in str(result["instructions"])
    assert result["completion"] is None


def test_prepare_assisted_publish_handoff_rejects_automatic_and_missing_scheduler_time(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            artist_profile = data["artist_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(artist_profile, ArtistProfile)

            automatic = SocialAccountConnection(
                organization=workspace,
                artist_profile=artist_profile,
                provider="instagram",
                username="@alpha-auto",
                connection_method=SocialAccountConnectionMethod.direct_api,
                status=SocialAccountConnectionStatus.connected,
                capabilities=["content_publish"],
            )
            session.add(automatic)
            await session.flush()

            item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Auto Reel",
                    content_type="video",
                    channels=[
                        MarketingContentChannelCreate(
                            channel="instagram",
                            social_account_connection_id=automatic.id,
                        )
                    ],
                ),
            )
            result = {"automatic_rejected": False, "naive_time_rejected": False}
            try:
                await prepare_assisted_publish_handoff(
                    session,
                    workspace.id,
                    item.id,
                    item.channels[0].id,
                    ManualPublishScheduleInput(
                        intended_publication_at=datetime(2026, 9, 15, 17, 30),
                    ),
                )
            except MarketingContentRelationshipError:
                result["naive_time_rejected"] = True
            try:
                await prepare_assisted_publish_handoff(
                    session,
                    workspace.id,
                    item.id,
                    item.channels[0].id,
                    ManualPublishScheduleInput(
                        intended_publication_at=datetime(
                            2026, 9, 15, 17, 30, tzinfo=UTC
                        ),
                    ),
                )
            except MarketingContentRelationshipError:
                result["automatic_rejected"] = True
            return result

    assert asyncio.run(run()) == {
        "automatic_rejected": True,
        "naive_time_rejected": True,
    }


def test_manual_publish_task_persistence_is_intentionally_deferred() -> None:
    assert "manual_publish_tasks" not in Base.metadata.tables


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
        (MarketingContentItemStatus.draft, MarketingContentItemStatus.cancelled),
        (MarketingContentItemStatus.draft, MarketingContentItemStatus.archived),
        (MarketingContentItemStatus.in_review, MarketingContentItemStatus.draft),
        (MarketingContentItemStatus.in_review, MarketingContentItemStatus.cancelled),
        (MarketingContentItemStatus.in_review, MarketingContentItemStatus.archived),
        (MarketingContentItemStatus.approved, MarketingContentItemStatus.draft),
        (MarketingContentItemStatus.approved, MarketingContentItemStatus.cancelled),
        (MarketingContentItemStatus.approved, MarketingContentItemStatus.archived),
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
            except MarketingContentLifecycleError:
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
            approved = await _submit_and_approve_content(session, workspace.id, item.id)
            draft = await transition_status(session, workspace.id, item.id, "draft")
            approval_cleared = (
                draft.approved_at is None and draft.approved_by_profile_id is None
            )
            await _submit_and_approve_content(session, workspace.id, item.id)
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
                approved.approved_at is not None and approved.approved_revision == 1,
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
            approved = await _submit_and_approve_content(session, workspace.id, item.id)
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


def test_marketing_content_service_rejects_material_edits_to_published_content(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, MarketingContentItemStatus, int, int | None]:
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
                    title="Published",
                    content_type="image",
                    scheduled_at=datetime(2026, 9, 10, tzinfo=UTC),
                ),
            )
            await _submit_and_approve_content(session, workspace.id, item.id)
            await transition_status(session, workspace.id, item.id, "scheduled")
            published = await transition_status(
                session, workspace.id, item.id, "published"
            )
            denied = False
            try:
                await update_content_item(
                    session,
                    workspace.id,
                    item.id,
                    MarketingContentItemUpdate(
                        title="Published Edited",
                        material_change=True,
                    ),
                )
            except MarketingContentLifecycleError:
                denied = True
            await session.refresh(published)
            return (
                denied,
                published.status,
                published.content_revision,
                published.approved_revision,
            )

    assert asyncio.run(run()) == (
        True,
        MarketingContentItemStatus.published,
        1,
        1,
    )


def test_marketing_content_service_routes_legacy_submit_and_approve_to_queue(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[str, str, int, bool, bool, list[str]]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            reviewer = await _seed_authorized_actor(
                session,
                workspace=workspace,
                email="queue-reviewer@example.com",
                capability_keys=[Capability.marketing_content_approve.value],
            )
            item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Queue Routed",
                    content_type="image",
                ),
            )
            submitted = await transition_status(
                session,
                workspace.id,
                item.id,
                "in_review",
            )
            request = await session.scalar(
                select(ApprovalRequest).where(
                    ApprovalRequest.resource_id == item.id,
                    ApprovalRequest.resource_revision == submitted.content_revision,
                )
            )
            assert request is not None
            submitted_request_status = request.status.value
            duplicate_denied = False
            try:
                await submit_resource_for_approval(
                    session,
                    workspace.id,
                    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                    item.id,
                )
            except ApprovalDuplicateActiveRequestError:
                duplicate_denied = True
            approved = await transition_status(
                session,
                workspace.id,
                item.id,
                "approved",
                actor=reviewer.id,
            )
            history = await get_approval_history(session, workspace.id, request.id)
            return (
                submitted_request_status,
                approved.status.value,
                approved.approved_revision or 0,
                submitted.approval_requested_at is not None,
                duplicate_denied,
                [decision.decision.value for decision in history],
            )

    assert asyncio.run(run()) == (
        "in_review",
        "approved",
        1,
        True,
        True,
        ["submitted", "approved"],
    )


def test_marketing_content_service_request_changes_edit_and_resubmit_preserves_history(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[str, int, int, list[str], list[str]]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            reviewer = await _seed_authorized_actor(
                session,
                workspace=workspace,
                email="changes-reviewer@example.com",
                capability_keys=[Capability.marketing_content_approve.value],
            )
            item = await create_content_item(
                session,
                workspace.id,
                MarketingContentItemCreate(
                    campaign_id=campaign.id,
                    title="Needs Changes",
                    content_type="caption",
                ),
            )
            await transition_status(session, workspace.id, item.id, "in_review")
            original = await session.scalar(
                select(ApprovalRequest).where(ApprovalRequest.resource_id == item.id)
            )
            assert original is not None
            await request_changes(
                session,
                workspace.id,
                original.id,
                actor=reviewer,
                comment="Tighten CTA.",
            )
            changed_item = await update_content_item(
                session,
                workspace.id,
                item.id,
                MarketingContentItemUpdate(
                    copy_text="Updated CTA.",
                    material_change=True,
                ),
            )
            resubmitted = await transition_status(
                session,
                workspace.id,
                item.id,
                "in_review",
            )
            new_request = await session.scalar(
                select(ApprovalRequest)
                .where(ApprovalRequest.resource_id == item.id)
                .where(
                    ApprovalRequest.resource_revision == changed_item.content_revision
                )
            )
            assert new_request is not None
            original_history = await get_approval_history(
                session, workspace.id, original.id
            )
            new_history = await get_approval_history(
                session, workspace.id, new_request.id
            )
            return (
                changed_item.status.value,
                original.resource_revision,
                resubmitted.content_revision,
                [decision.decision.value for decision in original_history],
                [decision.decision.value for decision in new_history],
            )

    assert asyncio.run(run()) == (
        "in_review",
        1,
        2,
        ["submitted", "changes_requested"],
        ["submitted"],
    )


def test_marketing_content_service_revisions_noops_channels_and_invalidation(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[int, int, int, int, str | None, list[str], int]:
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
                    title="Revisioned",
                    content_type="image",
                    channels=[MarketingContentChannelCreate(channel="instagram")],
                ),
            )
            noop = await update_content_item(
                session,
                workspace.id,
                item.id,
                MarketingContentItemUpdate(title="Revisioned", material_change=True),
            )
            noop_revision = noop.content_revision
            channel_noop = await replace_channels(
                session,
                workspace.id,
                item.id,
                [MarketingContentChannelCreate(channel="instagram")],
            )
            channel_noop_revision = channel_noop.content_revision
            channel_changed = await replace_channels(
                session,
                workspace.id,
                item.id,
                [MarketingContentChannelCreate(channel="tiktok")],
            )
            channel_changed_revision = channel_changed.content_revision
            approved = await _submit_and_approve_content(
                session,
                workspace.id,
                item.id,
            )
            request_id = approved.approval_request_id
            assert request_id is not None
            invalidated = await update_content_item(
                session,
                workspace.id,
                item.id,
                MarketingContentItemUpdate(title="Revisioned 2", material_change=True),
            )
            history = await get_approval_history(session, workspace.id, request_id)
            approval_event_count = await session.scalar(
                select(func.count(RealtimeEvent.id))
                .where(RealtimeEvent.organization_id == workspace.id)
                .where(RealtimeEvent.event_type == "approval.updated")
                .where(RealtimeEvent.entity_id == str(request_id))
            )
            return (
                noop_revision,
                channel_noop_revision,
                channel_changed_revision,
                invalidated.content_revision,
                invalidated.approval_request_id,
                [decision.decision.value for decision in history],
                approval_event_count or 0,
            )

    assert asyncio.run(run()) == (
        1,
        1,
        2,
        3,
        None,
        ["submitted", "approved", "invalidated"],
        3,
    )


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
            await _submit_and_approve_content(session, workspace.id, item.id)
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
                    scheduled_at=datetime(2026, 9, 10, tzinfo=UTC),
                    material_change=True,
                ),
            )
            await _submit_and_approve_content(session, workspace.id, item.id)
            scheduled = await transition_status(
                session,
                workspace.id,
                item.id,
                "scheduled",
            )
            return rejected, scheduled.status

    assert asyncio.run(run()) == (True, MarketingContentItemStatus.scheduled)


def test_marketing_content_service_denies_scheduling_for_stale_approval(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> bool:
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
                    title="Stale Schedule",
                    content_type="image",
                    scheduled_at=datetime(2026, 9, 10, tzinfo=UTC),
                ),
            )
            approved = await _submit_and_approve_content(session, workspace.id, item.id)
            approved.content_revision += 1
            await session.commit()
            try:
                await transition_status(session, workspace.id, item.id, "scheduled")
            except MarketingContentLifecycleError:
                return True
            return False

    assert asyncio.run(run()) is True


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


@pytest.mark.parametrize("entrypoint", ["replace", "combined", "single"])
@pytest.mark.parametrize(
    "field",
    [
        "copy_text_override",
        "scheduled_at",
        "social_account_connection_id",
        "asset_refs",
        "placement",
    ],
)
def test_channel_material_edits_preserve_identity_and_invalidate_approval(
    sessionmaker, entrypoint, field
):
    async def run():
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace_id = data["workspace"].id
            original_destination = SocialAccountConnection(
                organization=data["workspace"],
                artist_profile=data["artist_profile"],
                provider="instagram",
                username="@original-target",
                status=SocialAccountConnectionStatus.connected,
                capabilities=["manual_publish"],
            )
            session.add(original_destination)
            await session.flush()
            original_destination_id = original_destination.id
            item = await create_content_item(
                session,
                workspace_id,
                MarketingContentItemCreate(
                    campaign_id=data["campaign"].id,
                    title="Stable",
                    content_type="image",
                    channels=[
                        MarketingContentChannelCreate(
                            channel="instagram",
                            social_account_connection_id=original_destination_id,
                        ),
                        MarketingContentChannelCreate(channel="threads"),
                    ],
                ),
            )
            item_id = item.id
            original_ids = {row.channel: row.id for row in item.channels}
            destination = SocialAccountConnection(
                organization=data["workspace"],
                artist_profile=data["artist_profile"],
                provider="instagram",
                username="@new-target",
                status=SocialAccountConnectionStatus.connected,
                capabilities=["manual_publish"],
            )
            session.add(destination)
            await session.commit()
            proposed = {
                "copy_text_override": "Edited copy",
                "scheduled_at": datetime(2026, 10, 1, 12, tzinfo=UTC),
                "social_account_connection_id": destination.id,
                "asset_refs": [{"id": "new-asset"}],
                "placement": "story",
            }[field]
            approved = await _submit_and_approve_content(session, workspace_id, item_id)
            request_id = approved.approval_request_id
            revision = approved.content_revision
            if entrypoint == "single":
                await update_channel(
                    session,
                    workspace_id,
                    item_id,
                    original_ids["instagram"],
                    MarketingContentChannelUpdate(**{field: proposed}),
                )
            else:
                channels = [
                    MarketingContentChannelCreate(channel="threads"),
                    MarketingContentChannelCreate(
                        channel="instagram",
                        **{
                            "social_account_connection_id": original_destination_id,
                            field: proposed,
                        },
                    ),
                ]
                if entrypoint == "replace":
                    await replace_channels(session, workspace_id, item_id, channels)
                else:
                    await update_content_item_with_channels(
                        session,
                        workspace_id,
                        item_id,
                        MarketingContentItemUpdate(
                            title="Also edited", material_change=True
                        ),
                        channels,
                    )
            session.expire_all()
            reloaded = await get_content_item(session, workspace_id, item_id)
            assert [row.channel for row in reloaded.channels] == [
                "instagram",
                "threads",
            ]
            changed, unchanged = reloaded.channels
            assert unchanged.id == original_ids["threads"]
            if field == "placement":
                assert changed.id != original_ids["instagram"]
            else:
                assert changed.id == original_ids["instagram"]
            actual = getattr(changed, field)
            if isinstance(actual, datetime):
                actual = actual.replace(tzinfo=UTC)
            assert actual == proposed
            assert reloaded.content_revision == revision + 1
            assert reloaded.status == MarketingContentItemStatus.draft
            assert reloaded.approved_at is None
            assert reloaded.approval_request_id is None
            history = await get_approval_history(session, workspace_id, request_id)
            assert [entry.decision.value for entry in history] == [
                "submitted",
                "approved",
                "invalidated",
            ]

    asyncio.run(run())


@pytest.mark.parametrize("entrypoint", ["replace", "combined", "single"])
@pytest.mark.parametrize("failure_point", ["event", "invalidation"])
def test_failed_channel_reconciliation_rolls_back_channels_parent_and_approval(
    sessionmaker, monkeypatch, entrypoint, failure_point
):
    from labelos_api.services import content_invalidation, marketing_content_service

    async def run():
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace_id = data["workspace"].id
            item = await create_content_item(
                session,
                workspace_id,
                MarketingContentItemCreate(
                    campaign_id=data["campaign"].id,
                    title="Original",
                    content_type="image",
                    channels=[
                        MarketingContentChannelCreate(channel="instagram"),
                        MarketingContentChannelCreate(channel="threads"),
                    ],
                ),
            )
            item_id = item.id
            original_ids = [row.id for row in item.channels]
            approved = await _submit_and_approve_content(session, workspace_id, item_id)
            request_id = approved.approval_request_id
            revision = approved.content_revision
            event_count = await session.scalar(select(func.count(RealtimeEvent.id)))

            async def fail_after_channel_flush(*args, **kwargs):
                raise RuntimeError("Injected failure after channel flush")

            monkeypatch.setattr(
                (
                    marketing_content_service
                    if failure_point == "event"
                    else content_invalidation
                ),
                (
                    "_publish_content_event"
                    if failure_point == "event"
                    else "invalidate_content_channels"
                ),
                fail_after_channel_flush,
            )
            channels = [
                MarketingContentChannelCreate(
                    channel="instagram", copy_text_override="Edit"
                ),
                MarketingContentChannelCreate(channel="tiktok"),
            ]
            with pytest.raises(RuntimeError, match="after channel flush"):
                if entrypoint == "replace":
                    await replace_channels(session, workspace_id, item_id, channels)
                elif entrypoint == "single":
                    await update_channel(
                        session,
                        workspace_id,
                        item_id,
                        original_ids[0],
                        MarketingContentChannelUpdate(placement="story"),
                    )
                else:
                    await update_content_item_with_channels(
                        session,
                        workspace_id,
                        item_id,
                        MarketingContentItemUpdate(
                            title="Changed", material_change=True
                        ),
                        channels,
                    )
            # The service restores the transaction without requiring caller rollback.
            assert session.is_active
            await session.commit()
        async with sessionmaker() as session:
            reloaded = await get_content_item(session, workspace_id, item_id)
            assert [row.id for row in reloaded.channels] == original_ids
            assert reloaded.channels[0].copy_text_override is None
            assert reloaded.title == "Original"
            assert reloaded.content_revision == revision
            assert reloaded.status == MarketingContentItemStatus.approved
            assert reloaded.approval_request_id == request_id
            history = await get_approval_history(session, workspace_id, request_id)
            assert [entry.decision.value for entry in history] == [
                "submitted",
                "approved",
            ]
            assert (
                await session.scalar(select(func.count(RealtimeEvent.id)))
                == event_count
            )

    asyncio.run(run())


@pytest.mark.parametrize("entrypoint", ["replace", "combined", "single"])
@pytest.mark.parametrize("edit", ["timezone", "time", "legacy"])
def test_schedule_edits_invalidate_once_with_prior_context(
    sessionmaker, monkeypatch, entrypoint, edit
):
    from labelos_api.services import content_invalidation

    async def run():
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace_id = data["workspace"].id
            original = dict(
                channel="instagram",
                schedule_timezone="UTC",
                schedule_local_time="2027-06-15T16:30",
            )
            if edit == "legacy":
                original = dict(
                    channel="instagram",
                    scheduled_at=datetime(2027, 6, 15, 16, 30, tzinfo=UTC),
                )
            item = await create_content_item(
                session,
                workspace_id,
                MarketingContentItemCreate(
                    campaign_id=data["campaign"].id,
                    title="Schedule",
                    content_type="image",
                    channels=[MarketingContentChannelCreate(**original)],
                ),
            )
            item_id, channel_id = item.id, item.channels[0].id
            approved = await _submit_and_approve_content(session, workspace_id, item_id)
            revision, request_id = (
                approved.content_revision,
                approved.approval_request_id,
            )
            calls = []

            async def capture(active_session, invalidation, *, actor):
                assert active_session is session
                assert item.channels[0].schedule_timezone == (
                    None if edit == "legacy" else "UTC"
                )
                assert item.content_revision == revision
                calls.append(invalidation)

            monkeypatch.setattr(
                content_invalidation, "invalidate_content_channels", capture
            )
            await replace_channels(
                session,
                workspace_id,
                item_id,
                [MarketingContentChannelCreate(**original)],
            )
            assert calls == []
            assert item.channels[0].schedule_generation == 1
            assert item.content_revision == revision
            assert item.approval_request_id == request_id
            change = dict(
                channel="instagram",
                schedule_timezone=(
                    "America/Los_Angeles" if edit == "timezone" else "UTC"
                ),
                schedule_local_time=(
                    "2027-06-15T09:30" if edit == "timezone" else "2027-06-15T17:30"
                ),
            )
            if edit == "legacy":
                change["schedule_local_time"] = "2027-06-15T16:30"
            if entrypoint == "single":
                await update_channel(
                    session,
                    workspace_id,
                    item_id,
                    channel_id,
                    MarketingContentChannelUpdate(**change),
                )
            elif entrypoint == "combined":
                await update_content_item_with_channels(
                    session,
                    workspace_id,
                    item_id,
                    MarketingContentItemUpdate(title="Changed", material_change=True),
                    [MarketingContentChannelCreate(**change)],
                )
            else:
                await replace_channels(
                    session,
                    workspace_id,
                    item_id,
                    [MarketingContentChannelCreate(**change)],
                )
            result = await get_content_item(session, workspace_id, item_id)
            assert result.channels[0].id == channel_id
            assert result.channels[0].schedule_generation == 2
            assert result.content_revision == revision + 1
            assert result.status == MarketingContentItemStatus.draft
            assert result.approved_revision == revision
            assert result.approved_revision != result.content_revision
            assert len(calls) == 1
            assert calls[0].previous_content_revision == revision
            assert calls[0].previous_approval_request_id == request_id
            assert calls[0].materially_changed_channel_ids == (channel_id,)
            assert calls[0].removed_channel_ids == ()
            history = await get_approval_history(session, workspace_id, request_id)
            assert history[-1].decision.value == "invalidated"

    asyncio.run(run())


def test_service_rejects_naive_schedule(sessionmaker):
    from labelos_api.scheduling.timezones import ScheduleValidationError

    async def run():
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            with pytest.raises(ScheduleValidationError) as error:
                await create_content_item(
                    session,
                    data["workspace"].id,
                    MarketingContentItemCreate(
                        campaign_id=data["campaign"].id,
                        title="Naive",
                        content_type="image",
                        channels=[
                            MarketingContentChannelCreate(
                                channel="instagram", scheduled_at=datetime(2027, 1, 1)
                            )
                        ],
                    ),
                )
            assert error.value.code == "timestamp_timezone_required"

    asyncio.run(run())


def test_material_invalidation_hook_captures_old_authority_and_removals_before_delete(
    sessionmaker, monkeypatch
):
    from labelos_api.services import content_invalidation

    async def run():
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace_id = data["workspace"].id
            item = await create_content_item(
                session,
                workspace_id,
                MarketingContentItemCreate(
                    campaign_id=data["campaign"].id,
                    title="Hook",
                    content_type="image",
                    channels=[
                        MarketingContentChannelCreate(channel=name)
                        for name in ("instagram", "threads", "tiktok")
                    ],
                ),
            )
            item_id = item.id
            ids = {row.channel: row.id for row in item.channels}
            approved = await _submit_and_approve_content(session, workspace_id, item_id)
            old_revision, approval_id = (
                approved.content_revision,
                approved.approval_request_id,
            )
            calls = []

            async def capture(active_session, invalidation, *, actor):
                assert active_session is session
                assert (
                    await session.get(MarketingContentItemChannel, ids["threads"])
                    is not None
                )
                assert item.content_revision == old_revision
                calls.append(invalidation)

            monkeypatch.setattr(
                content_invalidation, "invalidate_content_channels", capture
            )
            channels = [
                MarketingContentChannelCreate(channel=name)
                for name in ("tiktok", "threads", "instagram")
            ]
            await replace_channels(session, workspace_id, item_id, channels)
            await update_channel(
                session,
                workspace_id,
                item_id,
                ids["tiktok"],
                MarketingContentChannelUpdate(external_post_id="result-only"),
            )
            assert calls == []
            await replace_channels(
                session,
                workspace_id,
                item_id,
                [
                    MarketingContentChannelCreate(
                        channel="instagram", copy_text_override="Edit"
                    ),
                    MarketingContentChannelCreate(
                        channel="tiktok", external_post_id="result-only"
                    ),
                    MarketingContentChannelCreate(channel="youtube"),
                ],
            )
            assert len(calls) == 1
            invalidation = calls[0]
            assert invalidation.workspace_id == workspace_id
            assert invalidation.content_item_id == item_id
            assert invalidation.previous_content_revision == old_revision
            assert invalidation.previous_approval_request_id == approval_id
            assert invalidation.previous_channel_ids == tuple(sorted(ids.values()))
            assert invalidation.materially_changed_channel_ids == (ids["instagram"],)
            assert invalidation.removed_channel_ids == (ids["threads"],)
            assert (
                await session.get(MarketingContentItemChannel, ids["threads"]) is None
            )

    asyncio.run(run())


@pytest.mark.parametrize("entrypoint", ["replace", "combined"])
def test_approved_channel_noop_keeps_identity_revision_and_approval(
    sessionmaker, entrypoint
):
    async def run():
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace_id = data["workspace"].id
            channels = [
                MarketingContentChannelCreate(
                    channel="instagram",
                    scheduled_at=datetime(2026, 10, 1, tzinfo=UTC),
                )
            ]
            item = await create_content_item(
                session,
                workspace_id,
                MarketingContentItemCreate(
                    campaign_id=data["campaign"].id,
                    title="Approved",
                    content_type="image",
                    channels=channels,
                ),
            )
            item_id = item.id
            channel_id = item.channels[0].id
            approved = await _submit_and_approve_content(session, workspace_id, item_id)
            request_id = approved.approval_request_id
            session.expire_all()
            if entrypoint == "replace":
                item = await replace_channels(session, workspace_id, item_id, channels)
            else:
                item = await update_content_item_with_channels(
                    session,
                    workspace_id,
                    item_id,
                    MarketingContentItemUpdate(),
                    channels,
                )
            assert item.channels[0].id == channel_id
            assert item.content_revision == 1
            assert item.status == MarketingContentItemStatus.approved
            assert item.approval_request_id == request_id
            assert item.approved_at is not None
            history = await get_approval_history(session, workspace_id, request_id)
            assert [entry.decision.value for entry in history] == [
                "submitted",
                "approved",
            ]

    asyncio.run(run())
