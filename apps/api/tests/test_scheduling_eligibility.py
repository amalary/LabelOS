import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from labelos_database.base import Base
from labelos_database.models import (
    ApprovalDecision,
    ApprovalDecisionValue,
    ApprovalRequest,
    ApprovalRequestStatus,
    Artist,
    ArtistProfile,
    Campaign,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    Organization,
    SocialAccountConnection,
    SocialAccountConnectionMethod,
    SocialAccountConnectionStatus,
    UniversalProfile,
    User,
)
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.api.v1.marketing_content import _content_response
from labelos_api.repositories import approvals, marketing_content
from labelos_api.scheduling.contracts import ApprovalEvidence, SchedulingFeatureControls
from labelos_api.services import scheduling_eligibility
from labelos_api.services.marketing_content_service import (
    MarketingContentLifecycleError,
    transition_status,
)
from labelos_api.services.scheduling_eligibility import (
    SchedulingExecutionMode,
    current_approval_matches,
    evaluate_channel_eligibility,
    evaluate_content_batch,
    planning_can_schedule,
)

ENABLED = SchedulingFeatureControls(
    execution_enabled=True, delivery_receiver_configured=True
)
INSTANT = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)


def _inputs():
    workspace_id, item_id, request_id, account_id = (uuid4() for _ in range(4))
    channel = MarketingContentItemChannel(
        id=uuid4(),
        marketing_content_item_id=item_id,
        channel="instagram",
        placement="feed",
        social_account_connection_id=account_id,
        scheduled_at=INSTANT,
        schedule_timezone="America/New_York",
        schedule_local_time="2026-11-01T01:30:00",
        schedule_offset_seconds=-18000,
    )
    item = MarketingContentItem(
        id=item_id,
        organization_id=workspace_id,
        campaign_id=uuid4(),
        title="Release teaser",
        content_type="post",
        content_revision=2,
        approved_revision=2,
        approval_request_id=request_id,
        status=MarketingContentItemStatus.approved,
        channels=[channel],
    )
    connection = SocialAccountConnection(
        id=account_id,
        organization_id=workspace_id,
        provider="instagram",
        status=SocialAccountConnectionStatus.connected,
        connection_method=SocialAccountConnectionMethod.direct_api,
        capabilities=["content_publish"],
    )
    return dict(
        workspace_id=workspace_id,
        item=item,
        channel=channel,
        connection=connection,
        effective_artist_id=None,
        evidence=ApprovalEvidence(
            request_id=request_id,
            workspace_id=workspace_id,
            resource_type="marketing_content_item",
            content_item_id=item_id,
            content_revision=2,
            status=ApprovalRequestStatus.approved,
            invalidated=False,
        ),
        execution_mode=SchedulingExecutionMode.automatic,
        controls=ENABLED,
    )


def test_valid_eligibility_and_exact_authority():
    values = _inputs()
    result = evaluate_channel_eligibility(**values)
    assert result.eligible and result.automatic_handoff_eligible
    assert result.content_revision == 2
    assert result.approval_request_id == values["evidence"].request_id
    assert result.scheduled_for == INSTANT
    assert result.schedule_timezone == "America/New_York"
    assert result.destination_resolution.usable
    assert not result.manual_handoff_required
    assert not result.reason_codes and not result.explanations
    # Missing denormalized pointer is allowed; a contradictory pointer is not.
    values["item"].approval_request_id = None
    assert evaluate_channel_eligibility(**values).eligible


@pytest.mark.parametrize(
    ("target", "field", "value", "reason"),
    [
        ("item", "approved_revision", 1, "stale_approval"),
        ("item", "content_revision", 3, "stale_approval"),
        ("item", "approval_request_id", uuid4(), "stale_approval"),
        ("item", "organization_id", uuid4(), "workspace_mismatch"),
        ("channel", "marketing_content_item_id", uuid4(), "channel_mismatch"),
        ("channel", "scheduled_at", None, "missing_schedule_intent"),
        ("channel", "schedule_timezone", None, "timezone_required"),
        ("channel", "schedule_timezone", "PST", "invalid_timezone"),
        ("channel", "schedule_local_time", None, "local_time_required"),
        ("channel", "schedule_offset_seconds", 0, "timezone_instant_mismatch"),
        ("channel", "schedule_offset_seconds", None, "disambiguation_required"),
        (
            "channel",
            "scheduled_at",
            INSTANT.replace(tzinfo=None),
            "timestamp_timezone_required",
        ),
        (
            "channel",
            "scheduled_at",
            INSTANT + timedelta(hours=1),
            "timezone_instant_mismatch",
        ),
        ("channel", "social_account_connection_id", uuid4(), "destination_mismatch"),
        ("connection", "provider", "youtube", "destination_mismatch"),
        ("connection", "organization_id", uuid4(), "destination_mismatch"),
        (
            "connection",
            "status",
            SocialAccountConnectionStatus.limited,
            "connection_unavailable",
        ),
        (
            "connection",
            "status",
            SocialAccountConnectionStatus.error,
            "connection_unavailable",
        ),
        (
            "connection",
            "status",
            SocialAccountConnectionStatus.disconnected,
            "connection_unavailable",
        ),
        (
            "connection",
            "status",
            SocialAccountConnectionStatus.pending,
            "reconnect_required",
        ),
        (
            "connection",
            "last_error_code",
            "provider_unavailable",
            "connection_unavailable",
        ),
        (
            "connection",
            "capabilities",
            ["account_analytics_read"],
            "capability_unavailable",
        ),
        ("connection", "capabilities", ["manual_publish"], "manual_delivery_required"),
    ],
)
def test_ineligible_inputs(target, field, value, reason):
    values = _inputs()
    setattr(values[target], field, value)
    result = evaluate_channel_eligibility(**values)
    assert not result.eligible and not result.automatic_handoff_eligible
    assert reason in result.reason_codes
    assert len(result.reason_codes) == len(result.explanations)
    if field == "organization_id":
        assert result.destination_resolution is None


@pytest.mark.parametrize("status", list(MarketingContentItemStatus))
def test_lifecycle(status):
    values = _inputs()
    values["item"].status = status
    result = evaluate_channel_eligibility(**values)
    assert result.eligible == (
        status
        in {MarketingContentItemStatus.approved, MarketingContentItemStatus.scheduled}
    )


@pytest.mark.parametrize(
    "change",
    [
        {"invalidated": True},
        {"content_revision": 1},
        {"workspace_id": uuid4()},
        {"content_item_id": uuid4()},
        {"resource_type": "other"},
        {"status": ApprovalRequestStatus.in_review},
    ],
)
def test_rejects_invalid_approval_evidence(change):
    values = _inputs()
    values["evidence"] = replace(values["evidence"], **change)
    assert "stale_approval" in evaluate_channel_eligibility(**values).reason_codes


def test_planning_remains_separate_from_execution_and_missing_destination():
    values = _inputs()
    values["channel"].scheduled_at = None
    values["channel"].schedule_timezone = None
    values["channel"].social_account_connection_id = None
    values["connection"] = None
    values["item"].scheduled_at = INSTANT
    assert planning_can_schedule(values["item"], approval_current=True)
    assert not evaluate_channel_eligibility(**values).eligible
    values = _inputs()
    values["controls"] = SchedulingFeatureControls()
    result = evaluate_channel_eligibility(**values)
    assert result.reason_codes == (
        "execution_disabled",
        "missing_durable_delivery_receiver",
    )
    values["controls"] = ENABLED
    values["execution_mode"] = SchedulingExecutionMode.manual
    assert not evaluate_channel_eligibility(**values).eligible
    values["execution_mode"] = SchedulingExecutionMode.disabled
    assert not evaluate_channel_eligibility(**values).eligible


def test_manual_health_priority_and_safe_diagnostics():
    values = _inputs()
    values["connection"].capabilities = ["manual_publish"]
    values["connection"].status = SocialAccountConnectionStatus.error
    values["connection"].last_error_message = "secret provider diagnostic"
    values["connection"].credential_ref = "private credential reference"
    result = evaluate_channel_eligibility(**values)
    assert result.manual_handoff_required
    assert result.reason_codes == ("connection_unavailable", "manual_delivery_required")
    assert "secret" not in str(result.projection())
    assert "private" not in str(result.projection())


def test_resolver_readiness_is_required_even_with_automatic_capability(monkeypatch):
    values = _inputs()
    destination = evaluate_channel_eligibility(**values).destination_resolution
    monkeypatch.setattr(
        scheduling_eligibility,
        "resolved_destination_for_connection",
        lambda *args, **kwargs: replace(destination, usable=False),
    )
    result = evaluate_channel_eligibility(**values)
    assert not result.eligible
    assert result.reason_codes == ("connection_unavailable",)


def test_existing_artist_mapping_and_dst_invalid_intent():
    values = _inputs()
    artist_id = uuid4()
    values["effective_artist_id"] = artist_id
    values["connection"].artist_profile_id = uuid4()
    values["connection"].artist_profile = ArtistProfile(artist_id=artist_id)
    assert evaluate_channel_eligibility(**values).eligible
    values["connection"].artist_profile.artist_id = uuid4()
    assert "destination_mismatch" in evaluate_channel_eligibility(**values).reason_codes
    values["connection"].artist_profile_id = None
    values["channel"].schedule_local_time = "2026-03-08T02:30:00"
    assert (
        "nonexistent_local_time" in evaluate_channel_eligibility(**values).reason_codes
    )
    values = _inputs()
    values["expected_content_revision"] = 1
    assert (
        "stale_content_revision" in evaluate_channel_eligibility(**values).reason_codes
    )


def test_repository_authority_batch_queries_and_read_only_projection(
    database_test_engine,
):
    async def run():
        engine = database_test_engine
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            organization = Organization(
                name="Label",
                slug=f"label-{uuid4()}",
                owner=User(email=f"{uuid4()}@example.com"),
            )
            artist = Artist(name="Artist", organization=organization)
            profile = ArtistProfile(
                artist=artist,
                universal_profile=UniversalProfile(
                    slug=f"artist-{uuid4()}", user=User(email=f"{uuid4()}@example.com")
                ),
            )
            campaign = Campaign(
                name="Campaign", organization=organization, primary_artist=artist
            )
            account = SocialAccountConnection(
                organization=organization,
                artist_profile=profile,
                provider="instagram",
                status=SocialAccountConnectionStatus.connected,
                capabilities=["content_publish"],
                connection_method=SocialAccountConnectionMethod.direct_api,
            )
            session.add_all([organization, campaign, account])
            await session.flush()
            items = []
            for index in range(4):
                values = _inputs()
                item = values["item"]
                item.organization_id = organization.id
                item.campaign_id = campaign.id
                item.approval_request_id = None
                item.channels[0].social_account_connection_id = account.id
                session.add(item)
                await session.flush()
                request = ApprovalRequest(
                    organization_id=organization.id,
                    resource_type="marketing_content_item",
                    resource_id=item.id,
                    resource_revision=2,
                    title=f"Approval {index}",
                    status=ApprovalRequestStatus.approved,
                    resolved_at=INSTANT,
                )
                session.add(request)
                await session.flush()
                item.approval_request_id = request.id
                items.append(item)
            await session.commit()
            first_id, workspace_id = items[0].id, organization.id
            session.expunge_all()
            page = await marketing_content.list_items_by_workspace(
                session, workspace_id, limit=100, offset=0
            )
            statements = []

            def capture(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)

            event.listen(engine.sync_engine, "before_cursor_execute", capture)
            try:
                one = await evaluate_content_batch(
                    session,
                    workspace_id,
                    page.items[:1],
                    controls=ENABLED,
                    execution_mode=SchedulingExecutionMode.automatic,
                )
                one_count = len(statements)
                statements.clear()
                batch = await evaluate_content_batch(
                    session,
                    workspace_id,
                    page.items,
                    controls=ENABLED,
                    execution_mode=SchedulingExecutionMode.automatic,
                )
                assert len(statements) == one_count == 3
                assert all(
                    channel.eligible
                    for item in batch.values()
                    for channel in item.channels.values()
                )
                assert not session.dirty and not session.new
                assert not any(
                    "credential_ref" in statement for statement in statements
                )
                assert len(one) == 1
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", capture)
            first = next(item for item in page.items if item.id == first_id)
            historical_id = first.approval_request_id
            # An active older request still outranks a newer approved history row.
            active = ApprovalRequest(
                organization_id=workspace_id,
                resource_type="marketing_content_item",
                resource_id=first.id,
                resource_revision=2,
                title="Active",
                status=ApprovalRequestStatus.in_review,
                created_at=INSTANT - timedelta(days=1000),
            )
            session.add(active)
            await session.flush()
            evidence = await approvals.load_current_approval_evidence(
                session, workspace_id, "marketing_content_item", [(first.id, 2)]
            )
            selected = await approvals.find_conflicting_or_resolved_request(
                session, workspace_id, "marketing_content_item", first.id, 2
            )
            assert evidence[first.id].request_id == selected.id == active.id
            assert not current_approval_matches(first, workspace_id, evidence[first.id])
            readiness = await evaluate_content_batch(session, workspace_id, [first])
            response = _content_response(first, readiness[first.id])
            assert not response.approval_state.can_schedule
            assert (
                "stale_approval"
                in response.channels[0].scheduling_eligibility["reason_codes"]
            )
            active.status = ApprovalRequestStatus.cancelled
            await session.flush()
            evidence = await approvals.load_current_approval_evidence(
                session, workspace_id, "marketing_content_item", [(first.id, 2)]
            )
            assert evidence[first.id].request_id == historical_id
            session.add(
                ApprovalDecision(
                    organization_id=workspace_id,
                    approval_request_id=historical_id,
                    decision=ApprovalDecisionValue.invalidated,
                    actor_kind="user",
                    actor_key="test-author",
                )
            )
            await session.flush()
            evidence = await approvals.load_current_approval_evidence(
                session, workspace_id, "marketing_content_item", [(first.id, 2)]
            )
            assert evidence[first.id].invalidated
            assert not current_approval_matches(first, workspace_id, evidence[first.id])
            with pytest.raises(
                MarketingContentLifecycleError, match="completed approval"
            ):
                await transition_status(
                    session,
                    workspace_id,
                    first.id,
                    MarketingContentItemStatus.scheduled,
                )
            # The latest resolved request, even when cancelled, is authoritative.
            active.created_at = datetime(2099, 1, 1, tzinfo=UTC)
            await session.flush()
            evidence = await approvals.load_current_approval_evidence(
                session, workspace_id, "marketing_content_item", [(first.id, 2)]
            )
            assert evidence[first.id].request_id == active.id
            assert evidence[first.id].status == ApprovalRequestStatus.cancelled

    asyncio.run(run())
