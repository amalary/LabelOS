import asyncio
from collections.abc import Iterator
from uuid import uuid4

import pytest
from labelos_database.base import Base
from labelos_database.models import (
    Artist,
    Campaign,
    CampaignGoal,
    CampaignMilestone,
    CampaignStatus,
    CampaignType,
    Organization,
    Release,
    UniversalProfile,
    User,
    WorkspaceMembership,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.services.campaign_service import (
    CampaignCreate,
    CampaignGoalCreate,
    CampaignGoalUpdate,
    CampaignLifecycleError,
    CampaignMilestoneCreate,
    CampaignMilestoneUpdate,
    CampaignNotFoundError,
    CampaignPlanningItemNotFoundError,
    CampaignRelationshipError,
    CampaignUpdate,
    add_campaign_member,
    archive_campaign,
    archive_campaign_goal,
    archive_campaign_milestone,
    associate_artist,
    associate_release,
    change_campaign_status,
    complete_campaign_milestone,
    create_campaign,
    create_campaign_goal,
    create_campaign_milestone,
    delete_campaign_goal,
    delete_campaign_milestone,
    get_campaign_by_id,
    list_campaign_goals,
    list_campaign_milestones,
    list_workspace_campaigns,
    remove_artist_association,
    remove_campaign_member,
    remove_release_association,
    update_campaign,
    update_campaign_goal,
    update_campaign_milestone,
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
        slug="alpha-campaign-service",
        owner=User(email="owner-alpha-service@example.com"),
    )
    other_workspace = Organization(
        name="Beta Label",
        slug="beta-campaign-service",
        owner=User(email="owner-beta-service@example.com"),
    )
    creator_profile = UniversalProfile(
        user=User(email="creator-alpha-service@example.com"),
        slug="creator-alpha-service",
    )
    owner_profile = UniversalProfile(
        user=User(email="lead-alpha-service@example.com"),
        slug="lead-alpha-service",
    )
    other_profile = UniversalProfile(
        user=User(email="lead-beta-service@example.com"),
        slug="lead-beta-service",
    )
    workspace_membership = WorkspaceMembership(
        workspace=workspace,
        profile=creator_profile,
    )
    owner_membership = WorkspaceMembership(
        workspace=workspace,
        profile=owner_profile,
    )
    other_membership = WorkspaceMembership(
        workspace=other_workspace,
        profile=other_profile,
    )
    artist = Artist(name="Alpha Artist", organization=workspace)
    other_artist = Artist(name="Beta Artist", organization=other_workspace)
    release = Release(title="Alpha Release", organization=workspace, artist=artist)
    other_release = Release(
        title="Beta Release",
        organization=other_workspace,
        artist=other_artist,
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
            other_membership,
            release,
            other_campaign,
        ]
    )
    await session.flush()
    return {
        "workspace": workspace,
        "other_workspace": other_workspace,
        "creator_profile": creator_profile,
        "owner_profile": owner_profile,
        "other_profile": other_profile,
        "workspace_membership": workspace_membership,
        "owner_membership": owner_membership,
        "other_membership": other_membership,
        "artist": artist,
        "other_artist": other_artist,
        "release": release,
        "other_release": other_release,
        "other_campaign": other_campaign,
    }


def test_campaign_service_creates_lists_gets_and_updates_campaigns(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[str, CampaignType, CampaignStatus, list[str], str | None]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            creator_profile = data["creator_profile"]
            owner_profile = data["owner_profile"]
            artist = data["artist"]
            release = data["release"]
            assert isinstance(workspace, Organization)
            assert isinstance(creator_profile, UniversalProfile)
            assert isinstance(owner_profile, UniversalProfile)
            assert isinstance(artist, Artist)
            assert isinstance(release, Release)

            created = await create_campaign(
                session,
                workspace.id,
                CampaignCreate(
                    name="Launch Plan",
                    description="Initial brief",
                    campaign_type="release",
                    status="planning",
                    created_by_user_id=creator_profile.user_id,
                    created_by_profile_id=creator_profile.id,
                    owner_profile_id=owner_profile.id,
                    primary_artist_id=artist.id,
                    release_id=release.id,
                ),
            )
            loaded = await get_campaign_by_id(session, workspace.id, created.id)
            loaded_name = loaded.name
            updated = await update_campaign(
                session,
                workspace.id,
                created.id,
                CampaignUpdate(
                    name="Launch Plan Updated",
                    campaign_type=CampaignType.marketing,
                    owner_profile_id=creator_profile.id,
                ),
            )
            listed = await list_workspace_campaigns(session, workspace.id)

            return (
                loaded_name,
                updated.campaign_type,
                updated.status,
                [campaign.name for campaign in listed],
                updated.description,
            )

    name, campaign_type, status, names, description = asyncio.run(run())

    assert name == "Launch Plan"
    assert campaign_type == CampaignType.marketing
    assert status == CampaignStatus.planning
    assert names == ["Launch Plan Updated"]
    assert description == "Initial brief"


def test_campaign_service_enforces_workspace_isolation_for_campaign_records(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[list[str], bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            other_workspace = data["other_workspace"]
            other_campaign = data["other_campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(other_workspace, Organization)
            assert isinstance(other_campaign, Campaign)

            created = await create_campaign(
                session,
                workspace.id,
                CampaignCreate(name="Alpha Campaign"),
            )
            visible = await list_workspace_campaigns(session, workspace.id)

            blocked_get = False
            try:
                await get_campaign_by_id(session, workspace.id, other_campaign.id)
            except CampaignNotFoundError:
                blocked_get = True
            try:
                await update_campaign(
                    session,
                    other_workspace.id,
                    created.id,
                    CampaignUpdate(name="Cross Workspace Edit"),
                )
            except CampaignNotFoundError:
                return [campaign.name for campaign in visible], blocked_get
            raise AssertionError("Expected cross-workspace update to be blocked")

    names, blocked_get = asyncio.run(run())

    assert names == ["Alpha Campaign"]
    assert blocked_get is True


def test_campaign_service_rejects_invalid_campaign_relationships(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, bool, bool, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            other_profile = data["other_profile"]
            other_artist = data["other_artist"]
            other_release = data["other_release"]
            assert isinstance(workspace, Organization)
            assert isinstance(other_profile, UniversalProfile)
            assert isinstance(other_artist, Artist)
            assert isinstance(other_release, Release)

            missing_user_rejected = False
            outside_profile_rejected = False
            outside_artist_rejected = False
            outside_release_rejected = False

            try:
                await create_campaign(
                    session,
                    workspace.id,
                    CampaignCreate(
                        name="Missing User",
                        created_by_user_id=uuid4(),
                    ),
                )
            except CampaignRelationshipError:
                missing_user_rejected = True

            try:
                await create_campaign(
                    session,
                    workspace.id,
                    CampaignCreate(
                        name="Outside Profile",
                        owner_profile_id=other_profile.id,
                    ),
                )
            except CampaignRelationshipError:
                outside_profile_rejected = True

            try:
                await create_campaign(
                    session,
                    workspace.id,
                    CampaignCreate(
                        name="Outside Artist",
                        primary_artist_id=other_artist.id,
                    ),
                )
            except CampaignRelationshipError:
                outside_artist_rejected = True

            try:
                await create_campaign(
                    session,
                    workspace.id,
                    CampaignCreate(
                        name="Outside Release",
                        release_id=other_release.id,
                    ),
                )
            except CampaignRelationshipError:
                outside_release_rejected = True

            return (
                missing_user_rejected,
                outside_profile_rejected,
                outside_artist_rejected,
                outside_release_rejected,
            )

    result = asyncio.run(run())

    assert result == (True, True, True, True)


def test_campaign_service_manages_member_artist_and_release_associations(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[str, str, str, bool, bool, bool, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            workspace_membership = data["workspace_membership"]
            other_membership = data["other_membership"]
            artist = data["artist"]
            release = data["release"]
            other_release = data["other_release"]
            assert isinstance(workspace, Organization)
            assert isinstance(workspace_membership, WorkspaceMembership)
            assert isinstance(other_membership, WorkspaceMembership)
            assert isinstance(artist, Artist)
            assert isinstance(release, Release)
            assert isinstance(other_release, Release)

            campaign = await create_campaign(
                session,
                workspace.id,
                CampaignCreate(name="Relationship Campaign"),
            )
            member_link = await add_campaign_member(
                session,
                workspace.id,
                campaign.id,
                workspace_membership.id,
                participation_status="confirmed",
            )
            artist_link = await associate_artist(
                session,
                workspace.id,
                campaign.id,
                artist.id,
                relationship_kind="primary",
            )
            release_link = await associate_release(
                session,
                workspace.id,
                campaign.id,
                release.id,
                relationship_kind="focus",
            )

            invalid_member = False
            invalid_release = False
            try:
                await add_campaign_member(
                    session,
                    workspace.id,
                    campaign.id,
                    other_membership.id,
                )
            except CampaignRelationshipError:
                invalid_member = True
            try:
                await associate_release(
                    session,
                    workspace.id,
                    campaign.id,
                    other_release.id,
                )
            except CampaignRelationshipError:
                invalid_release = True

            removed_member = await remove_campaign_member(
                session,
                workspace.id,
                campaign.id,
                workspace_membership.id,
            )
            removed_artist = await remove_artist_association(
                session,
                workspace.id,
                campaign.id,
                artist.id,
            )
            removed_release = await remove_release_association(
                session,
                workspace.id,
                campaign.id,
                release.id,
            )

            return (
                member_link.participation_status,
                artist_link.relationship_kind,
                release_link.relationship_kind,
                invalid_member,
                invalid_release,
                removed_member,
                removed_artist and removed_release,
            )

    result = asyncio.run(run())

    assert result == ("confirmed", "primary", "focus", True, True, True, True)


def test_campaign_service_validates_lifecycle_transitions(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[CampaignStatus, CampaignStatus, bool, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            assert isinstance(workspace, Organization)

            campaign = await create_campaign(
                session,
                workspace.id,
                CampaignCreate(name="Lifecycle Campaign"),
            )
            planning = await change_campaign_status(
                session,
                workspace.id,
                campaign.id,
                CampaignStatus.planning,
            )
            planning_status = planning.status
            active = await change_campaign_status(
                session,
                workspace.id,
                campaign.id,
                "active",
            )

            invalid_transition_rejected = False
            invalid_status_rejected = False
            try:
                await change_campaign_status(
                    session,
                    workspace.id,
                    campaign.id,
                    CampaignStatus.draft,
                )
            except CampaignLifecycleError:
                invalid_transition_rejected = True
            try:
                await change_campaign_status(
                    session,
                    workspace.id,
                    campaign.id,
                    "unknown",
                )
            except CampaignLifecycleError:
                invalid_status_rejected = True

            archived = await archive_campaign(session, workspace.id, campaign.id)
            return (
                planning_status,
                archived.status,
                active.status == CampaignStatus.archived,
                invalid_transition_rejected and invalid_status_rejected,
            )

    planning_status, archived_status, active_reference_status, rejected = asyncio.run(
        run()
    )

    assert planning_status == CampaignStatus.planning
    assert archived_status == CampaignStatus.archived
    assert active_reference_status is True
    assert rejected is True


def test_campaign_service_manages_goals_and_milestones(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[str, str, str, bool, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            creator_profile = data["creator_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(creator_profile, UniversalProfile)

            campaign = await create_campaign(
                session,
                workspace.id,
                CampaignCreate(name="Planning Campaign"),
            )
            goal = await create_campaign_goal(
                session,
                workspace.id,
                campaign.id,
                CampaignGoalCreate(
                    title="Grow audience",
                    target_value="10000 pre-saves",
                ),
            )
            updated_goal = await update_campaign_goal(
                session,
                workspace.id,
                campaign.id,
                goal.id,
                CampaignGoalUpdate(
                    title="Grow launch audience",
                    success_criteria="Hit pre-save target before release week",
                ),
            )
            archived_goal = await archive_campaign_goal(
                session,
                workspace.id,
                campaign.id,
                goal.id,
            )

            milestone = await create_campaign_milestone(
                session,
                workspace.id,
                campaign.id,
                CampaignMilestoneCreate(
                    title="Finalize creative",
                    created_by_user_id=creator_profile.user_id,
                ),
            )
            completed = await complete_campaign_milestone(
                session,
                workspace.id,
                campaign.id,
                milestone.id,
            )
            archived_milestone = await archive_campaign_milestone(
                session,
                workspace.id,
                campaign.id,
                milestone.id,
            )

            goals = await list_campaign_goals(session, workspace.id, campaign.id)
            milestones = await list_campaign_milestones(
                session,
                workspace.id,
                campaign.id,
            )

            return (
                updated_goal.title,
                archived_goal.status,
                archived_milestone.status,
                completed.completed_at is not None,
                goals == [goal] and milestones == [milestone],
            )

    result = asyncio.run(run())

    assert result == (
        "Grow launch audience",
        "archived",
        "archived",
        True,
        True,
    )


def test_campaign_service_deletes_planning_items_and_blocks_cross_workspace_access(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, bool, bool, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            other_workspace = data["other_workspace"]
            other_campaign = data["other_campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(other_workspace, Organization)
            assert isinstance(other_campaign, Campaign)

            campaign = await create_campaign(
                session,
                workspace.id,
                CampaignCreate(name="Scoped Planning Campaign"),
            )
            goal = await create_campaign_goal(
                session,
                workspace.id,
                campaign.id,
                CampaignGoalCreate(title="Scoped goal"),
            )
            milestone = await create_campaign_milestone(
                session,
                workspace.id,
                campaign.id,
                CampaignMilestoneCreate(title="Scoped milestone"),
            )
            other_goal = CampaignGoal(
                campaign_id=other_campaign.id,
                title="Outside goal",
            )
            other_milestone = CampaignMilestone(
                campaign_id=other_campaign.id,
                title="Outside milestone",
            )
            session.add_all([other_goal, other_milestone])
            await session.commit()

            cross_goal_blocked = False
            cross_milestone_blocked = False
            try:
                await update_campaign_goal(
                    session,
                    workspace.id,
                    other_campaign.id,
                    other_goal.id,
                    CampaignGoalUpdate(title="Blocked"),
                )
            except CampaignNotFoundError:
                cross_goal_blocked = True
            try:
                await update_campaign_milestone(
                    session,
                    workspace.id,
                    other_campaign.id,
                    other_milestone.id,
                    CampaignMilestoneUpdate(title="Blocked"),
                )
            except CampaignNotFoundError:
                cross_milestone_blocked = True

            deleted_goal = await delete_campaign_goal(
                session,
                workspace.id,
                campaign.id,
                goal.id,
            )
            deleted_milestone = await delete_campaign_milestone(
                session,
                workspace.id,
                campaign.id,
                milestone.id,
            )

            missing_goal_blocked = False
            try:
                await update_campaign_goal(
                    session,
                    workspace.id,
                    campaign.id,
                    goal.id,
                    CampaignGoalUpdate(title="Missing"),
                )
            except CampaignPlanningItemNotFoundError:
                missing_goal_blocked = True

            return (
                deleted_goal,
                deleted_milestone,
                cross_goal_blocked and cross_milestone_blocked,
                missing_goal_blocked,
            )

    assert asyncio.run(run()) == (True, True, True, True)
