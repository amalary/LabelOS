import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from labelos_database.base import Base
from labelos_database.capabilities import Capability
from labelos_database.models import (
    ApprovalRequestStatus,
    ApprovalStageStatus,
    Artist,
    Campaign,
    MarketingContentItem,
    MarketingContentItemStatus,
    MembershipRole,
    Organization,
    OrganizationMembership,
    RealtimeEvent,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspacePermission,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.authorization import ActorKind, AuthorizationActor
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
)
from labelos_api.services import approval_service
from labelos_api.services.approval_service import (
    ApprovalAgentDecisionDeniedError,
    ApprovalAlreadyResolvedError,
    ApprovalDuplicateActiveRequestError,
    ApprovalMissingCapabilityError,
    ApprovalRequestNotFoundError,
    ApprovalResourceNotFoundError,
    ApprovalSelfApprovalError,
    ApprovalStaleResourceRevisionError,
    ApprovalUnsupportedResourceTypeError,
    approve_request,
    assign_stage_reviewer,
    cancel_request,
    get_approval_history,
    get_approval_request,
    invalidate_request,
    list_approval_requests,
    reject_request,
    request_changes,
    resubmit_resource,
    submit_resource_for_approval,
)
from labelos_api.services.marketing_content_service import (
    MarketingContentItemCreate,
    MarketingContentItemUpdate,
    MarketingContentLifecycleError,
    create_content_item,
    transition_status,
    update_content_item,
)


@dataclass(frozen=True)
class ApprovalServiceSeed:
    organization_id: UUID
    other_organization_id: UUID
    campaign_id: UUID
    content_item_id: UUID
    other_content_item_id: UUID
    submitter: User
    reviewer: User
    second_reviewer: User
    viewer: User
    no_capability_user: User
    other_workspace_user: User
    submitter_profile_id: UUID
    reviewer_profile_id: UUID
    other_workspace_profile_id: UUID


@dataclass(frozen=True)
class AgentActor:
    user: User
    authorization_actor: AuthorizationActor


def _agent_actor(user: User, *, execution_id: str = "exec_approval_test") -> AgentActor:
    return AgentActor(
        user=user,
        authorization_actor=AuthorizationActor(
            kind=ActorKind.ai_agent,
            subject=f"agent:marketing:{execution_id}",
            user_id=user.id,
        ),
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


async def _seed_actor(
    session: AsyncSession,
    *,
    workspace: Organization,
    email: str,
    capabilities: tuple[str, ...],
) -> tuple[User, UniversalProfile]:
    user = User(email=email)
    profile = UniversalProfile(user=user, slug=f"{email.split('@')[0]}-{uuid4().hex}")
    membership = OrganizationMembership(
        organization=workspace,
        user=user,
        role=MembershipRole.guest,
        workspace_permission=WorkspacePermission.guest,
        department_access=["marketing"],
        capability_permissions=list(capabilities),
    )
    workspace_membership = WorkspaceMembership(
        workspace=workspace,
        profile=profile,
        organization_membership=membership,
        status="active",
    )
    session.add_all([user, profile, membership, workspace_membership])
    await session.flush()
    return user, profile


async def _seed(session: AsyncSession) -> ApprovalServiceSeed:
    organization = Organization(
        name="Alpha Label",
        slug=f"alpha-approval-service-{uuid4().hex}",
        owner=User(email=f"owner-{uuid4().hex}@example.com"),
    )
    other_organization = Organization(
        name="Beta Label",
        slug=f"beta-approval-service-{uuid4().hex}",
        owner=User(email=f"owner-{uuid4().hex}@example.com"),
    )
    artist = Artist(name="Alpha Artist", organization=organization)
    campaign = Campaign(
        name="Alpha Campaign",
        organization=organization,
        primary_artist=artist,
    )
    item = MarketingContentItem(
        organization=organization,
        campaign=campaign,
        artist=artist,
        title="Launch Caption",
        content_type="caption",
        status=MarketingContentItemStatus.draft,
    )
    other_item = MarketingContentItem(
        organization=organization,
        campaign=campaign,
        title="Other Caption",
        content_type="caption",
        status=MarketingContentItemStatus.draft,
    )
    session.add_all([item, other_item])
    await session.flush()

    submitter, submitter_profile = await _seed_actor(
        session,
        workspace=organization,
        email=f"submitter-{uuid4().hex}@example.com",
        capabilities=(
            Capability.marketing_content_submit_for_review.value,
            Capability.marketing_content_view.value,
            Capability.marketing_content_create.value,
            Capability.marketing_content_edit.value,
            Capability.marketing_content_approve.value,
        ),
    )
    reviewer, reviewer_profile = await _seed_actor(
        session,
        workspace=organization,
        email=f"reviewer-{uuid4().hex}@example.com",
        capabilities=(Capability.marketing_content_approve.value,),
    )
    second_reviewer, _ = await _seed_actor(
        session,
        workspace=organization,
        email=f"second-reviewer-{uuid4().hex}@example.com",
        capabilities=(Capability.marketing_content_approve.value,),
    )
    viewer, _ = await _seed_actor(
        session,
        workspace=organization,
        email=f"viewer-{uuid4().hex}@example.com",
        capabilities=(Capability.marketing_content_view.value,),
    )
    no_capability_user, _ = await _seed_actor(
        session,
        workspace=organization,
        email=f"none-{uuid4().hex}@example.com",
        capabilities=(),
    )
    other_workspace_user, other_workspace_profile = await _seed_actor(
        session,
        workspace=other_organization,
        email=f"outsider-{uuid4().hex}@example.com",
        capabilities=(Capability.marketing_content_approve.value,),
    )
    item.created_by_user_id = submitter.id
    item.created_by_profile_id = submitter_profile.id
    other_item.created_by_user_id = submitter.id
    other_item.created_by_profile_id = submitter_profile.id
    await session.flush()
    return ApprovalServiceSeed(
        organization_id=organization.id,
        other_organization_id=other_organization.id,
        campaign_id=campaign.id,
        content_item_id=item.id,
        other_content_item_id=other_item.id,
        submitter=submitter,
        reviewer=reviewer,
        second_reviewer=second_reviewer,
        viewer=viewer,
        no_capability_user=no_capability_user,
        other_workspace_user=other_workspace_user,
        submitter_profile_id=submitter_profile.id,
        reviewer_profile_id=reviewer_profile.id,
        other_workspace_profile_id=other_workspace_profile.id,
    )


async def _submit(
    session: AsyncSession,
    seed: ApprovalServiceSeed,
):
    return await submit_resource_for_approval(
        session,
        seed.organization_id,
        MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
        seed.content_item_id,
        actor=seed.submitter,
        summary="Ready for review.",
    )


def test_approval_service_submission_get_list_assign_and_history(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[
        ApprovalRequestStatus,
        ApprovalStageStatus,
        MarketingContentItemStatus,
        int,
        bool,
        list[str],
        bool,
    ]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            request = await _submit(session, seed)
            loaded = await get_approval_request(
                session,
                seed.organization_id,
                request.id,
                actor=seed.viewer,
            )
            page = await list_approval_requests(
                session,
                seed.organization_id,
                actor=seed.viewer,
                limit=10,
            )
            assigned = await assign_stage_reviewer(
                session,
                seed.organization_id,
                request.id,
                seed.reviewer_profile_id,
                actor=seed.reviewer,
            )
            history = await get_approval_history(
                session,
                seed.organization_id,
                request.id,
                actor=seed.viewer,
            )
            item_status = await session.scalar(
                select(MarketingContentItem.status).where(
                    MarketingContentItem.id == seed.content_item_id
                )
            )
            event_payload = await session.scalar(
                select(RealtimeEvent.payload)
                .where(RealtimeEvent.event_type == "approval.updated")
                .order_by(RealtimeEvent.created_at.asc())
            )
            assert event_payload is not None
            return (
                loaded.status,
                loaded.stages[0].status,
                item_status,
                page.total,
                assigned.stages[0].assigned_profile_id == seed.reviewer_profile_id,
                [row.decision.value for row in history],
                event_payload["contentItemId"] == str(seed.content_item_id)
                and "reason" not in event_payload
                and "comment" not in event_payload,
            )

    assert asyncio.run(run()) == (
        ApprovalRequestStatus.in_review,
        ApprovalStageStatus.in_review,
        MarketingContentItemStatus.in_review,
        1,
        True,
        ["submitted"],
        True,
    )


def test_approval_service_approve_request_resolves_stage_request_and_projection(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[
        ApprovalRequestStatus,
        ApprovalStageStatus,
        MarketingContentItemStatus,
        int | None,
        list[str],
    ]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            request = await _submit(session, seed)
            approved = await approve_request(
                session,
                seed.organization_id,
                request.id,
                actor=seed.reviewer,
                comment="Looks good.",
            )
            item = await session.scalar(
                select(MarketingContentItem).where(
                    MarketingContentItem.id == seed.content_item_id
                )
            )
            assert item is not None
            history = await get_approval_history(
                session,
                seed.organization_id,
                request.id,
            )
            return (
                approved.status,
                approved.stages[0].status,
                item.status,
                item.approved_revision,
                [row.decision.value for row in history],
            )

    assert asyncio.run(run()) == (
        ApprovalRequestStatus.approved,
        ApprovalStageStatus.approved,
        MarketingContentItemStatus.approved,
        1,
        ["submitted", "approved"],
    )


def test_approval_service_request_changes_reject_cancel_and_invalidate_are_distinct(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> (
        tuple[tuple[str, str, str], tuple[str, str, str], tuple[str, str, str]]
    ):
        async with sessionmaker() as session:
            seed = await _seed(session)
            changes = await _submit(session, seed)
            changes = await request_changes(
                session,
                seed.organization_id,
                changes.id,
                actor=seed.reviewer,
                comment="Revise CTA.",
            )
            changes_history = await get_approval_history(
                session,
                seed.organization_id,
                changes.id,
            )

            reject_item = await session.get(
                MarketingContentItem,
                seed.other_content_item_id,
            )
            assert reject_item is not None
            reject_item.status = MarketingContentItemStatus.draft
            await session.commit()
            rejected = await submit_resource_for_approval(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                seed.other_content_item_id,
                actor=seed.submitter,
            )
            rejected = await reject_request(
                session,
                seed.organization_id,
                rejected.id,
                actor=seed.reviewer,
                comment="Cannot use.",
            )
            rejected_history = await get_approval_history(
                session,
                seed.organization_id,
                rejected.id,
            )

            cancel_item = MarketingContentItem(
                organization_id=seed.organization_id,
                campaign_id=seed.campaign_id,
                title="Cancel Me",
                content_type="caption",
                status=MarketingContentItemStatus.draft,
            )
            invalidate_item = MarketingContentItem(
                organization_id=seed.organization_id,
                campaign_id=seed.campaign_id,
                title="Invalidate Me",
                content_type="caption",
                status=MarketingContentItemStatus.draft,
            )
            session.add_all([cancel_item, invalidate_item])
            await session.commit()
            cancelled = await submit_resource_for_approval(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                cancel_item.id,
                actor=seed.submitter,
            )
            invalidated = await submit_resource_for_approval(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                invalidate_item.id,
                actor=seed.submitter,
            )
            cancelled = await cancel_request(
                session,
                seed.organization_id,
                cancelled.id,
                actor=seed.submitter,
                reason="No longer needed.",
            )
            invalidated = await invalidate_request(
                session,
                seed.organization_id,
                invalidated.id,
                actor=seed.submitter,
                reason="Material edit superseded this request.",
            )
            invalidated_history = await get_approval_history(
                session,
                seed.organization_id,
                invalidated.id,
            )
            return (
                (
                    changes.status.value,
                    changes.stages[0].status.value,
                    changes_history[-1].decision.value,
                ),
                (
                    rejected.status.value,
                    rejected.stages[0].status.value,
                    rejected_history[-1].decision.value,
                ),
                (
                    cancelled.stages[0].status.value,
                    invalidated.stages[0].status.value,
                    invalidated_history[-1].decision.value,
                ),
            )

    assert asyncio.run(run()) == (
        ("changes_requested", "changes_requested", "changes_requested"),
        ("rejected", "rejected", "rejected"),
        ("cancelled", "invalidated", "invalidated"),
    )


def test_approval_service_denies_invalid_actor_and_resource_boundaries(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, bool]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            result: dict[str, bool] = {}
            with pytest.raises(ApprovalMissingCapabilityError):
                await submit_resource_for_approval(
                    session,
                    seed.organization_id,
                    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                    seed.content_item_id,
                    actor=seed.no_capability_user,
                )
            result["submit_capability"] = True

            with pytest.raises(ApprovalResourceNotFoundError):
                await submit_resource_for_approval(
                    session,
                    seed.other_organization_id,
                    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                    seed.content_item_id,
                    actor=seed.other_workspace_user,
                )
            result["cross_org_resource"] = True

            with pytest.raises(ApprovalUnsupportedResourceTypeError):
                await submit_resource_for_approval(
                    session,
                    seed.organization_id,
                    "unknown_resource",
                    uuid4(),
                    actor=seed.submitter,
                )
            result["unsupported"] = True

            request = await _submit(session, seed)
            with pytest.raises(ApprovalDuplicateActiveRequestError):
                await submit_resource_for_approval(
                    session,
                    seed.organization_id,
                    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                    seed.content_item_id,
                    actor=seed.submitter,
                )
            result["duplicate"] = True

            with pytest.raises(ApprovalSelfApprovalError):
                await approve_request(
                    session,
                    seed.organization_id,
                    request.id,
                    actor=seed.submitter,
                )
            result["self_approval"] = True

            agent = _agent_actor(seed.reviewer, execution_id="copy-review")
            with pytest.raises(ApprovalAgentDecisionDeniedError):
                await approve_request(
                    session,
                    seed.organization_id,
                    request.id,
                    actor=agent,
                )
            result["agent_denied"] = True

            item = await session.get(MarketingContentItem, seed.content_item_id)
            assert item is not None
            item.content_revision += 1
            await session.commit()
            with pytest.raises(ApprovalStaleResourceRevisionError):
                await approve_request(
                    session,
                    seed.organization_id,
                    request.id,
                    actor=seed.reviewer,
                )
            result["stale"] = True

            with pytest.raises(ApprovalRequestNotFoundError):
                await get_approval_request(
                    session,
                    seed.organization_id,
                    uuid4(),
                    actor=seed.viewer,
                )
            result["not_found"] = True
            return result

    assert asyncio.run(run()) == {
        "submit_capability": True,
        "cross_org_resource": True,
        "unsupported": True,
        "duplicate": True,
        "self_approval": True,
        "agent_denied": True,
        "stale": True,
        "not_found": True,
    }


def test_approval_service_resubmit_targets_new_revision_and_preserves_history(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[int, int, list[str], list[str]]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            original = await _submit(session, seed)
            await request_changes(
                session,
                seed.organization_id,
                original.id,
                actor=seed.reviewer,
                comment="Edit copy.",
            )
            await update_content_item(
                session,
                seed.organization_id,
                seed.content_item_id,
                MarketingContentItemUpdate(
                    title="Launch Caption Edited",
                    material_change=True,
                ),
                actor=seed.submitter,
            )
            resubmitted = await resubmit_resource(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                seed.content_item_id,
                previous_approval_request_id=original.id,
                actor=seed.submitter,
                summary="Edited.",
            )
            original_history = await get_approval_history(
                session,
                seed.organization_id,
                original.id,
            )
            new_history = await get_approval_history(
                session,
                seed.organization_id,
                resubmitted.id,
            )
            return (
                original.resource_revision,
                resubmitted.resource_revision,
                [row.decision.value for row in original_history],
                [row.decision.value for row in new_history],
            )

    assert asyncio.run(run()) == (
        1,
        2,
        ["submitted", "changes_requested"],
        ["submitted", "resubmitted"],
    )


def test_approval_realtime_payload_covers_lifecycle_actions_without_private_comments(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[list[str], bool]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            request = await _submit(session, seed)
            await assign_stage_reviewer(
                session,
                seed.organization_id,
                request.id,
                seed.reviewer_profile_id,
                actor=seed.reviewer,
            )
            await request_changes(
                session,
                seed.organization_id,
                request.id,
                actor=seed.reviewer,
                comment="Private change note.",
            )
            await update_content_item(
                session,
                seed.organization_id,
                seed.content_item_id,
                MarketingContentItemUpdate(title="Edited", material_change=True),
                actor=seed.submitter,
            )
            resubmitted = await resubmit_resource(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                seed.content_item_id,
                previous_approval_request_id=request.id,
                actor=seed.submitter,
                summary="Private resubmit note.",
            )
            await approve_request(
                session,
                seed.organization_id,
                resubmitted.id,
                actor=seed.reviewer,
                comment="Private approval note.",
            )
            await update_content_item(
                session,
                seed.organization_id,
                seed.content_item_id,
                MarketingContentItemUpdate(title="Invalidated", material_change=True),
                actor=seed.submitter,
            )

            rejected = await submit_resource_for_approval(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                seed.other_content_item_id,
                actor=seed.submitter,
            )
            await reject_request(
                session,
                seed.organization_id,
                rejected.id,
                actor=seed.reviewer,
                comment="Private rejection note.",
            )

            cancel_item = MarketingContentItem(
                organization_id=seed.organization_id,
                campaign_id=seed.campaign_id,
                title="Cancel",
                content_type="caption",
                status=MarketingContentItemStatus.draft,
            )
            session.add(cancel_item)
            await session.commit()
            cancelled = await submit_resource_for_approval(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                cancel_item.id,
                actor=seed.submitter,
            )
            await cancel_request(
                session,
                seed.organization_id,
                cancelled.id,
                actor=seed.submitter,
                reason="Private cancellation note.",
            )

            payloads = (
                await session.scalars(
                    select(RealtimeEvent.payload)
                    .where(RealtimeEvent.event_type == "approval.updated")
                    .where(RealtimeEvent.organization_id == seed.organization_id)
                    .order_by(RealtimeEvent.created_at.asc(), RealtimeEvent.id.asc())
                )
            ).all()
            required_keys = {
                "approvalRequestId",
                "resourceType",
                "resourceId",
                "resourceRevision",
                "status",
                "stageStatus",
                "actorKind",
                "eventAction",
                "contentItemId",
                "campaignId",
                "timestamp",
            }
            safe = all(
                required_keys <= set(payload)
                and "reason" not in payload
                and "comment" not in payload
                for payload in payloads
            )
            return ([payload["eventAction"] for payload in payloads], safe)

    actions, safe = asyncio.run(run())
    assert {
        "submitted",
        "assigned",
        "changes_requested",
        "resubmitted",
        "approved",
        "invalidated",
        "rejected",
        "cancelled",
    } <= set(actions)
    assert safe is True


def test_marketing_agent_boundary_allows_submission_revision_and_resubmission_only(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[str, str, str, str, str, bool, bool, bool]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            agent = _agent_actor(seed.submitter, execution_id="exec_marketing_01")
            item = await create_content_item(
                session,
                seed.organization_id,
                MarketingContentItemCreate(
                    campaign_id=seed.campaign_id,
                    title="Agent Draft",
                    content_type="caption",
                    copy_text="Draft copy.",
                ),
                actor=agent,
            )
            request = await submit_resource_for_approval(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                item.id,
                actor=agent,
                metadata_json={"agentExecutionId": "exec_marketing_01"},
                expected_resource_revision=item.content_revision,
            )
            await request_changes(
                session,
                seed.organization_id,
                request.id,
                actor=seed.reviewer,
                comment="Make the CTA clearer.",
            )
            changed_feedback = await get_approval_history(
                session,
                seed.organization_id,
                request.id,
                actor=agent,
            )
            updated = await update_content_item(
                session,
                seed.organization_id,
                item.id,
                MarketingContentItemUpdate(
                    copy_text="Draft copy with a clearer CTA.",
                    material_change=True,
                ),
                actor=agent,
            )
            resubmitted = await resubmit_resource(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                item.id,
                previous_approval_request_id=request.id,
                actor=agent,
                expected_resource_revision=updated.content_revision,
                summary="Revised by agent execution exec_marketing_01.",
            )
            resubmitted_id = resubmitted.id

            decision_denied = False
            try:
                await approve_request(
                    session,
                    seed.organization_id,
                    resubmitted_id,
                    actor=agent,
                )
            except ApprovalAgentDecisionDeniedError:
                decision_denied = True

            approved = await approve_request(
                session,
                seed.organization_id,
                resubmitted_id,
                actor=seed.reviewer,
            )
            scheduling_denied = False
            try:
                await transition_status(
                    session,
                    seed.organization_id,
                    approved.resource_id,
                    MarketingContentItemStatus.scheduled,
                    actor=agent,
                )
            except MarketingContentLifecycleError:
                scheduling_denied = True

            cross_org_denied = False
            try:
                await submit_resource_for_approval(
                    session,
                    seed.other_organization_id,
                    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                    item.id,
                    actor=agent,
                )
            except ApprovalResourceNotFoundError:
                cross_org_denied = True

            first_decision = changed_feedback[0]
            latest_decision = (
                await get_approval_history(
                    session,
                    seed.organization_id,
                    resubmitted_id,
                )
            )[0]
            return (
                request.submitted_by_actor_kind,
                request.submitted_by_actor_key or "",
                first_decision.actor_kind,
                latest_decision.actor_key or "",
                changed_feedback[-1].reason or "",
                decision_denied,
                scheduling_denied,
                cross_org_denied,
            )

    assert asyncio.run(run()) == (
        "ai_agent",
        "agent:marketing:exec_marketing_01",
        "ai_agent",
        "agent:marketing:exec_marketing_01",
        "Make the CTA clearer.",
        True,
        True,
        True,
    )


def test_approval_service_rolls_back_transition_stage_decision_projection_and_event(
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> tuple[
        ApprovalRequestStatus,
        ApprovalStageStatus,
        MarketingContentItemStatus,
        int,
        int,
    ]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            request = await _submit(session, seed)
            request_id = request.id

            async def fail_publish(*_args, **_kwargs):
                raise RuntimeError("outbox unavailable")

            monkeypatch.setattr(
                approval_service.RealtimePublisher,
                "publish",
                fail_publish,
            )
            with pytest.raises(RuntimeError):
                await approve_request(
                    session,
                    seed.organization_id,
                    request_id,
                    actor=seed.reviewer,
                    comment="Looks good.",
                )
            await session.rollback()
            loaded = await get_approval_request(
                session, seed.organization_id, request_id
            )
            item = await session.get(MarketingContentItem, seed.content_item_id)
            event_count = await session.scalar(select(func.count(RealtimeEvent.id)))
            decision_count = len(
                await get_approval_history(session, seed.organization_id, request_id)
            )
            assert item is not None
            return (
                loaded.status,
                loaded.stages[0].status,
                item.status,
                decision_count,
                event_count or 0,
            )

    assert asyncio.run(run()) == (
        ApprovalRequestStatus.in_review,
        ApprovalStageStatus.in_review,
        MarketingContentItemStatus.in_review,
        1,
        1,
    )


def test_approval_service_second_resolution_is_stable_domain_conflict(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[ApprovalRequestStatus, bool, list[str]]:
        async with sessionmaker() as session:
            seed = await _seed(session)
            request = await _submit(session, seed)
            request_id = request.id

        async def decide(actor: User, approve: bool) -> ApprovalRequestStatus | str:
            async with sessionmaker() as session:
                try:
                    if approve:
                        resolved = await approve_request(
                            session,
                            seed.organization_id,
                            request_id,
                            actor=actor,
                        )
                    else:
                        resolved = await reject_request(
                            session,
                            seed.organization_id,
                            request_id,
                            actor=actor,
                        )
                    return resolved.status
                except ApprovalAlreadyResolvedError:
                    return "already_resolved"

        outcomes = await asyncio.gather(
            decide(seed.reviewer, True),
            decide(seed.second_reviewer, False),
        )
        async with sessionmaker() as session:
            history = await get_approval_history(
                session,
                seed.organization_id,
                request_id,
            )
            terminal_statuses = [
                outcome
                for outcome in outcomes
                if isinstance(outcome, ApprovalRequestStatus)
            ]
            assert len(terminal_statuses) == 1
            return (
                terminal_statuses[0],
                "already_resolved" in outcomes,
                [row.decision.value for row in history],
            )

    status, conflict, history = asyncio.run(run())
    assert status in {ApprovalRequestStatus.approved, ApprovalRequestStatus.rejected}
    assert conflict is True
    assert history in (["submitted", "approved"], ["submitted", "rejected"])
