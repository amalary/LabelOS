import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from labelos_database.base import Base
from labelos_database.capabilities import Capability
from labelos_database.models import (
    ApprovalDecisionValue,
    ApprovalRequestStatus,
    ApprovalStageStatus,
    Artist,
    Campaign,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    Organization,
    Release,
    UniversalProfile,
    User,
    WorkspaceMembership,
)
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.repositories import approvals
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
    UnsupportedApprovalResourceTypeError,
    get_approval_resource_adapter,
)


@dataclass(frozen=True)
class ApprovalSeed:
    organization_id: UUID
    outside_organization_id: UUID
    submitter_user_id: UUID
    submitter_profile_id: UUID
    reviewer_profile_id: UUID
    other_reviewer_profile_id: UUID
    campaign_id: UUID
    artist_id: UUID
    release_id: UUID
    content_item_id: UUID
    other_content_item_id: UUID
    outside_content_item_id: UUID


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


async def _seed(session: AsyncSession) -> ApprovalSeed:
    organization = Organization(
        name="Alpha Label",
        slug=f"alpha-approvals-{uuid4().hex}",
        owner=User(email=f"owner-{uuid4().hex}@example.com"),
    )
    outside_organization = Organization(
        name="Beta Label",
        slug=f"beta-approvals-{uuid4().hex}",
        owner=User(email=f"owner-{uuid4().hex}@example.com"),
    )
    submitter = User(email=f"submitter-{uuid4().hex}@example.com")
    submitter_profile = UniversalProfile(
        user=submitter,
        slug=f"submitter-{uuid4().hex}",
    )
    reviewer_profile = UniversalProfile(
        user=User(email=f"reviewer-{uuid4().hex}@example.com"),
        slug=f"reviewer-{uuid4().hex}",
    )
    other_reviewer_profile = UniversalProfile(
        user=User(email=f"other-reviewer-{uuid4().hex}@example.com"),
        slug=f"other-reviewer-{uuid4().hex}",
    )
    outside_profile = UniversalProfile(
        user=User(email=f"outside-reviewer-{uuid4().hex}@example.com"),
        slug=f"outside-reviewer-{uuid4().hex}",
    )
    artist = Artist(name="Alpha Artist", organization=organization)
    release = Release(title="Alpha Release", organization=organization, artist=artist)
    campaign = Campaign(
        name="Alpha Campaign",
        organization=organization,
        primary_artist=artist,
        release=release,
    )
    other_artist = Artist(name="Other Artist", organization=organization)
    other_campaign = Campaign(name="Other Campaign", organization=organization)
    outside_artist = Artist(name="Beta Artist", organization=outside_organization)
    outside_campaign = Campaign(
        name="Beta Campaign",
        organization=outside_organization,
        primary_artist=outside_artist,
    )
    item = MarketingContentItem(
        organization=organization,
        campaign=campaign,
        artist=artist,
        release=release,
        title="Launch Caption",
        content_type="caption",
        status=MarketingContentItemStatus.draft,
        created_by_user=submitter,
        created_by_profile=submitter_profile,
        channels=[
            MarketingContentItemChannel(channel="instagram", placement="feed"),
            MarketingContentItemChannel(channel="tiktok", placement="video"),
        ],
    )
    other_item = MarketingContentItem(
        organization=organization,
        campaign=other_campaign,
        artist=other_artist,
        title="Other Caption",
        content_type="caption",
        status=MarketingContentItemStatus.draft,
    )
    outside_item = MarketingContentItem(
        organization=outside_organization,
        campaign=outside_campaign,
        artist=outside_artist,
        title="Outside Caption",
        content_type="caption",
        status=MarketingContentItemStatus.draft,
    )
    session.add_all(
        [
            WorkspaceMembership(workspace=organization, profile=submitter_profile),
            WorkspaceMembership(workspace=organization, profile=reviewer_profile),
            WorkspaceMembership(workspace=organization, profile=other_reviewer_profile),
            WorkspaceMembership(
                workspace=outside_organization, profile=outside_profile
            ),
            item,
            other_item,
            outside_item,
        ]
    )
    await session.flush()
    return ApprovalSeed(
        organization_id=organization.id,
        outside_organization_id=outside_organization.id,
        submitter_user_id=submitter.id,
        submitter_profile_id=submitter_profile.id,
        reviewer_profile_id=reviewer_profile.id,
        other_reviewer_profile_id=other_reviewer_profile.id,
        campaign_id=campaign.id,
        artist_id=artist.id,
        release_id=release.id,
        content_item_id=item.id,
        other_content_item_id=other_item.id,
        outside_content_item_id=outside_item.id,
    )


async def _create_request_with_stage(
    session: AsyncSession,
    seed: ApprovalSeed,
    *,
    resource_id: UUID | None = None,
    assigned_profile_id: UUID | None = None,
    status: ApprovalRequestStatus = ApprovalRequestStatus.requested,
    submitted_at: datetime | None = None,
):
    request = await approvals.create_request(
        session,
        seed.organization_id,
        {
            "resource_type": MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
            "resource_id": resource_id or seed.content_item_id,
            "resource_revision": 1,
            "status": status,
            "requested_by_user_id": seed.submitter_user_id,
            "requested_by_profile_id": seed.submitter_profile_id,
            "submitted_by_actor_kind": "user",
            "submitted_by_actor_key": "submitter@example.com",
            "title": "Launch Caption",
            "summary": "Review launch caption.",
            "submitted_at": submitted_at or datetime.now(UTC),
        },
    )
    stage = await approvals.create_initial_stage(
        session,
        seed.organization_id,
        request.id,
        {
            "required_capability": Capability.marketing_content_approve.value,
            "assigned_profile_id": assigned_profile_id or seed.reviewer_profile_id,
        },
    )
    assert stage is not None
    return request, stage


def test_approval_repository_create_retrieve_and_relationship_loading(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, int, int]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            request, stage = await _create_request_with_stage(session, seed)
            first_decision = await approvals.append_decision(
                session,
                seed.organization_id,
                request.id,
                {
                    "stage_id": stage.id,
                    "decision": ApprovalDecisionValue.submitted,
                    "decided_by_user_id": seed.submitter_user_id,
                    "decided_by_profile_id": seed.submitter_profile_id,
                    "actor_kind": "user",
                    "actor_key": "submitter@example.com",
                    "reason": "Ready.",
                    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                },
            )
            assert first_decision is not None
            await session.commit()

            found = await approvals.get_request(
                session, seed.organization_id, request.id
            )
            loaded = await approvals.get_request_with_stages_and_decisions(
                session, seed.organization_id, request.id
            )
            denied = await approvals.get_request(
                session, seed.outside_organization_id, request.id
            )
            assert found is not None
            assert loaded is not None
            return denied is None, len(loaded.stages), len(loaded.decisions)

    assert asyncio.run(run()) == (True, 1, 1)


def test_approval_repository_active_lookup_duplicate_and_resolution_detection(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[UUID | None, bool, UUID | None, UUID | None]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            request, _stage = await _create_request_with_stage(session, seed)
            active = await approvals.find_active_request_for_resource_revision(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                seed.content_item_id,
                1,
            )
            request_id = request.id
            active_id = active.id if active is not None else None
            await session.commit()
            duplicate_raised = False
            with pytest.raises(approvals.DuplicateActiveApprovalRequestError):
                await approvals.create_request(
                    session,
                    seed.organization_id,
                    {
                        "resource_type": MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                        "resource_id": seed.content_item_id,
                        "resource_revision": 1,
                        "title": "Duplicate",
                    },
                )
            duplicate_raised = True
            await session.rollback()

            await approvals.update_request_lifecycle(
                session,
                seed.organization_id,
                request_id,
                status=ApprovalRequestStatus.approved,
                resolved_at=datetime.now(UTC),
            )
            active_after_resolution = (
                await approvals.find_active_request_for_resource_revision(
                    session,
                    seed.organization_id,
                    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                    seed.content_item_id,
                    1,
                )
            )
            resolved = await approvals.find_conflicting_or_resolved_request(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                seed.content_item_id,
                1,
            )
            return (
                active_id,
                duplicate_raised,
                active_after_resolution.id if active_after_resolution else None,
                resolved.id if resolved else None,
            )

    active_id, duplicate_raised, active_after_resolution_id, resolved_id = asyncio.run(
        run()
    )
    assert active_id is not None
    assert duplicate_raised is True
    assert active_after_resolution_id is None
    assert resolved_id == active_id


def test_approval_repository_append_only_history_ordering_and_lifecycle_updates(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[list[str], ApprovalRequestStatus, ApprovalStageStatus]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            request, stage = await _create_request_with_stage(session, seed)
            started = datetime(2026, 1, 1, tzinfo=UTC)
            completed = started + timedelta(minutes=5)
            await approvals.update_request_lifecycle(
                session,
                seed.organization_id,
                request.id,
                status=ApprovalRequestStatus.in_review,
                current_stage_order=1,
            )
            updated_stage = await approvals.update_stage_lifecycle(
                session,
                seed.organization_id,
                stage.id,
                status=ApprovalStageStatus.in_review,
                started_at=started,
            )
            assert updated_stage is not None
            for decision, created_at in (
                (ApprovalDecisionValue.submitted, started),
                (ApprovalDecisionValue.approved, completed),
            ):
                appended = await approvals.append_decision(
                    session,
                    seed.organization_id,
                    request.id,
                    {
                        "stage_id": stage.id,
                        "decision": decision,
                        "decided_by_profile_id": seed.reviewer_profile_id,
                        "actor_kind": "user",
                        "actor_key": "reviewer@example.com",
                        "created_at": created_at,
                    },
                )
                assert appended is not None
            await approvals.update_stage_lifecycle(
                session,
                seed.organization_id,
                stage.id,
                status=ApprovalStageStatus.approved,
                completed_at=completed,
            )
            decisions = await approvals.list_decisions_chronologically(
                session,
                seed.organization_id,
                request.id,
            )
            loaded = await approvals.get_request_with_stages_and_decisions(
                session, seed.organization_id, request.id
            )
            assert decisions is not None
            assert loaded is not None
            return (
                [decision.decision.value for decision in decisions],
                loaded.status,
                loaded.stages[0].status,
            )

    assert asyncio.run(run()) == (
        ["submitted", "approved"],
        ApprovalRequestStatus.in_review,
        ApprovalStageStatus.approved,
    )


def test_approval_repository_filters_pagination_and_reviewer_queries(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, list[UUID]]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            first, _ = await _create_request_with_stage(
                session,
                seed,
                assigned_profile_id=seed.reviewer_profile_id,
                submitted_at=datetime(2026, 1, 3, tzinfo=UTC),
            )
            second, _ = await _create_request_with_stage(
                session,
                seed,
                resource_id=seed.other_content_item_id,
                assigned_profile_id=seed.other_reviewer_profile_id,
                status=ApprovalRequestStatus.changes_requested,
                submitted_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
            approved, _ = await _create_request_with_stage(
                session,
                seed,
                resource_id=uuid4(),
                assigned_profile_id=seed.reviewer_profile_id,
                status=ApprovalRequestStatus.approved,
                submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
            page = await approvals.list_requests(
                session,
                seed.organization_id,
                limit=2,
                offset=0,
            )
            second_page = await approvals.list_requests(
                session,
                seed.organization_id,
                limit=2,
                offset=2,
            )
            status_filtered = await approvals.list_requests(
                session,
                seed.organization_id,
                status=ApprovalRequestStatus.changes_requested,
                limit=10,
                offset=0,
            )
            resource_filtered = await approvals.list_requests(
                session,
                seed.organization_id,
                resource_type=MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                limit=10,
                offset=0,
            )
            submitter_filtered = await approvals.list_requests(
                session,
                seed.organization_id,
                requested_by_profile_id=seed.submitter_profile_id,
                limit=10,
                offset=0,
            )
            reviewer_filtered = await approvals.list_requests(
                session,
                seed.organization_id,
                assigned_profile_id=seed.reviewer_profile_id,
                limit=10,
                offset=0,
            )
            current_reviewer_filtered = await approvals.list_requests(
                session,
                seed.organization_id,
                assigned_to_current_profile=True,
                current_profile_id=seed.other_reviewer_profile_id,
                limit=10,
                offset=0,
            )
            current_submitter_filtered = await approvals.list_requests(
                session,
                seed.organization_id,
                submitted_by_current_actor=True,
                current_actor_user_id=seed.submitter_user_id,
                limit=10,
                offset=0,
            )
            campaign_filtered = await approvals.list_requests(
                session,
                seed.organization_id,
                campaign_id=seed.campaign_id,
                limit=10,
                offset=0,
            )
            artist_filtered = await approvals.list_requests(
                session,
                seed.organization_id,
                artist_id=seed.artist_id,
                limit=10,
                offset=0,
            )
            return {
                "page": [item.id for item in page.items],
                "second_page": [item.id for item in second_page.items],
                "status": [item.id for item in status_filtered.items],
                "resource": [item.id for item in resource_filtered.items],
                "submitter": [item.id for item in submitter_filtered.items],
                "reviewer": [item.id for item in reviewer_filtered.items],
                "current_reviewer": [
                    item.id for item in current_reviewer_filtered.items
                ],
                "current_submitter": [
                    item.id for item in current_submitter_filtered.items
                ],
                "campaign": [item.id for item in campaign_filtered.items],
                "artist": [item.id for item in artist_filtered.items],
                "expected": [first.id, second.id, approved.id],
            }

    result = asyncio.run(run())
    first_id, second_id, approved_id = result["expected"]
    assert result["page"] == [first_id, second_id]
    assert result["second_page"] == [approved_id]
    assert result["status"] == [second_id]
    assert result["resource"] == [first_id, second_id, approved_id]
    assert result["submitter"] == [first_id, second_id, approved_id]
    assert result["reviewer"] == [first_id, approved_id]
    assert result["current_reviewer"] == [second_id]
    assert result["current_submitter"] == [first_id, second_id, approved_id]
    assert result["campaign"] == [first_id]
    assert result["artist"] == [first_id]


def test_approval_repository_rejects_unsupported_resource_type(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> None:
        async with sessionmaker() as session:
            seed = await _seed(session)
            with pytest.raises(UnsupportedApprovalResourceTypeError):
                await approvals.create_request(
                    session,
                    seed.organization_id,
                    {
                        "resource_type": "contracts",
                        "resource_id": uuid4(),
                        "title": "Unsafe",
                    },
                )
            with pytest.raises(UnsupportedApprovalResourceTypeError):
                await approvals.list_requests(
                    session,
                    seed.organization_id,
                    resource_type="contracts",
                    limit=10,
                    offset=0,
                )

    asyncio.run(run())


def test_marketing_content_approval_resource_adapter_summary(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[str, int, str, bool, bool, tuple[str, ...]]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            adapter = get_approval_resource_adapter(
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE
            )
            item = await adapter.resolve(
                session, seed.organization_id, seed.content_item_id
            )
            assert item is not None
            request, _ = await _create_request_with_stage(session, seed)
            summary = adapter.queue_summary(item)
            capability = adapter.capabilities.approve
            approved_current_before = adapter.approved_revision_is_current(
                item, request
            )
            item.approved_revision = item.content_revision
            approved_current_after = adapter.approved_revision_is_current(item, request)
            return (
                summary.title,
                summary.current_revision,
                capability,
                adapter.is_eligible_for_submission(item),
                approved_current_before is False and approved_current_after is True,
                tuple(channel.channel for channel in summary.channels),
            )

    assert asyncio.run(run()) == (
        "Launch Caption",
        1,
        "marketing.content.approve",
        True,
        True,
        ("instagram", "tiktok"),
    )


def test_approval_queue_loading_does_not_issue_obvious_n_plus_one_queries(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[int, int]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            for index in range(5):
                await _create_request_with_stage(
                    session,
                    seed,
                    resource_id=uuid4(),
                    assigned_profile_id=seed.reviewer_profile_id,
                    submitted_at=datetime(2026, 1, index + 1, tzinfo=UTC),
                )
            await session.commit()

        query_count = 0

        def count_query(*_args) -> None:
            nonlocal query_count
            query_count += 1

        engine = sessionmaker.kw["bind"].sync_engine
        event.listen(engine, "before_cursor_execute", count_query)
        try:
            async with sessionmaker() as session:
                page = await approvals.list_requests(
                    session,
                    seed.organization_id,
                    assigned_profile_id=seed.reviewer_profile_id,
                    limit=10,
                    offset=0,
                )
                after_load = query_count
                for request in page.items:
                    assert request.stages
                    assert request.stages[0].assigned_profile is not None
                    assert request.decisions == []
                    assert request.stages[0].decisions == []
                after_access = query_count
        finally:
            event.remove(engine, "before_cursor_execute", count_query)
        return after_load, after_access

    after_load, after_access = asyncio.run(run())
    assert after_load <= 7
    assert after_access == after_load
