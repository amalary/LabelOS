from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from itertools import product
from uuid import uuid4

import pytest
from labelos_database.models import ApprovalRequestStatus, MarketingContentItemStatus

from labelos_api.scheduling.contracts import (
    ApprovalEvidence,
    DeliveryAcceptanceReceipt,
    DeliveryAcceptanceRequest,
    DueDisposition,
    ScheduleSnapshot,
    SchedulingBlockedReason,
    SchedulingFeatureControls,
    SchedulingJobState,
    SchedulingOperation,
    approval_blocked_reason,
    due_disposition,
    schedule_blocked_reason,
    transition_target,
)


@pytest.fixture
def snapshot() -> ScheduleSnapshot:
    return ScheduleSnapshot(
        workspace_id=uuid4(),
        content_item_id=uuid4(),
        channel_id=uuid4(),
        content_revision=3,
        approval_request_id=uuid4(),
        schedule_generation=2,
        scheduled_for=datetime(2026, 9, 14, 12, tzinfo=UTC),
    )


@pytest.fixture
def evidence(snapshot: ScheduleSnapshot) -> ApprovalEvidence:
    return ApprovalEvidence(
        request_id=snapshot.approval_request_id,
        workspace_id=snapshot.workspace_id,
        resource_type="marketing_content_item",
        content_item_id=snapshot.content_item_id,
        content_revision=snapshot.content_revision,
        status=ApprovalRequestStatus.approved,
        invalidated=False,
    )


# Independent explicit specification of every edge in the architecture table.
LEGAL_EDGES = {
    (None, "activate"): "pending",
    ("pending", "claim"): "claimed",
    ("pending", "block"): "blocked",
    ("pending", "cancel"): "cancelled",
    ("pending", "supersede"): "superseded",
    ("claimed", "accept_delivery"): "handed_off",
    ("claimed", "block"): "blocked",
    ("claimed", "cancel"): "cancelled",
    ("claimed", "supersede"): "superseded",
    ("claimed", "recover_claim"): "pending",
    ("blocked", "revalidate"): "pending",
    ("blocked", "cancel"): "cancelled",
    ("blocked", "supersede"): "superseded",
}


@pytest.mark.parametrize(
    ("state", "operation"),
    list(product([None, *SchedulingJobState], SchedulingOperation)),
)
def test_all_transition_edges(state, operation):
    expected = LEGAL_EDGES.get((state, operation))
    if expected is None:
        with pytest.raises(ValueError, match="Illegal scheduling transition"):
            transition_target(state, operation)
    else:
        assert transition_target(state, operation) == expected


@pytest.mark.parametrize("parent_status", MarketingContentItemStatus)
def test_eligible_parent_states(snapshot, evidence, parent_status):
    result = approval_blocked_reason(
        snapshot,
        current_revision=3,
        approved_revision=3,
        parent_status=parent_status,
        evidence=evidence,
    )
    if parent_status in {
        MarketingContentItemStatus.approved,
        MarketingContentItemStatus.scheduled,
    }:
        assert result is None
    else:
        assert result == SchedulingBlockedReason.ineligible_parent_state


@pytest.mark.parametrize(
    "change",
    [
        {"request_id": uuid4()},
        {"workspace_id": uuid4()},
        {"resource_type": "another_resource"},
        {"content_item_id": uuid4()},
        {"content_revision": 2},
        {"invalidated": True},  # Current repository retains approved status.
        *[
            {"status": status}
            for status in ApprovalRequestStatus
            if status != ApprovalRequestStatus.approved
        ],
    ],
)
def test_rejects_wrong_or_invalidated_approval(snapshot, evidence, change):
    assert (
        approval_blocked_reason(
            snapshot,
            current_revision=3,
            approved_revision=3,
            parent_status=MarketingContentItemStatus.scheduled,
            evidence=replace(evidence, **change),
        )
        == SchedulingBlockedReason.stale_approval
    )


@pytest.mark.parametrize("approved_revision", [None, 2, 4])
def test_approval_evidence_does_not_override_revision_projection(
    snapshot, evidence, approved_revision
):
    assert (
        approval_blocked_reason(
            snapshot,
            current_revision=3,
            approved_revision=approved_revision,
            parent_status=MarketingContentItemStatus.approved,
            evidence=evidence,
        )
        == SchedulingBlockedReason.stale_approval
    )


def test_approval_projection_without_repository_evidence_is_insufficient(snapshot):
    assert (
        approval_blocked_reason(
            snapshot,
            current_revision=3,
            approved_revision=3,
            parent_status=MarketingContentItemStatus.approved,
            evidence=None,
        )
        == SchedulingBlockedReason.stale_approval
    )


def test_new_parent_revision_fences_unchanged_sibling_schedule(snapshot, evidence):
    assert (
        approval_blocked_reason(
            snapshot,
            current_revision=4,
            approved_revision=3,
            parent_status=MarketingContentItemStatus.draft,
            evidence=evidence,
        )
        == SchedulingBlockedReason.stale_content_revision
    )


@pytest.mark.parametrize(
    ("seconds_changed", "generation", "reason"),
    [
        (0, 2, None),
        (0, 3, SchedulingBlockedReason.changed_schedule_generation),
        (60, 2, SchedulingBlockedReason.changed_schedule_generation),
        (60, 3, SchedulingBlockedReason.changed_schedule_generation),
    ],
)
def test_schedule_snapshot_cannot_drift(snapshot, seconds_changed, generation, reason):
    assert (
        schedule_blocked_reason(
            snapshot,
            scheduled_at=snapshot.scheduled_for + timedelta(seconds=seconds_changed),
            schedule_generation=generation,
        )
        == reason
    )


def test_removed_schedule_cannot_execute(snapshot):
    assert (
        schedule_blocked_reason(snapshot, scheduled_at=None, schedule_generation=3)
        == SchedulingBlockedReason.missing_schedule_intent
    )


@pytest.mark.parametrize("window_seconds", [0, 37, 300, 900])
def test_lateness_inclusive_boundaries_and_no_early_claims(snapshot, window_seconds):
    now = snapshot.scheduled_for
    window = timedelta(seconds=window_seconds)
    for instant, expected in [
        (now + timedelta(microseconds=1), DueDisposition.future),
        (now, DueDisposition.claimable),
        (now - window, DueDisposition.claimable),
        (now - window - timedelta(microseconds=1), DueDisposition.missed),
    ]:
        assert (
            due_disposition(scheduled_for=instant, now=now, lateness_window=window)
            == expected
        )


def test_claim_does_not_extend_lateness_window(snapshot):
    instant = snapshot.scheduled_for
    window = timedelta(seconds=300)
    assert (
        due_disposition(
            scheduled_for=instant, now=instant + window, lateness_window=window
        )
        == DueDisposition.claimable
    )
    assert (
        due_disposition(
            scheduled_for=instant,
            now=instant + window + timedelta(microseconds=1),
            lateness_window=window,
        )
        == DueDisposition.missed
    )


def test_invalid_lateness_config_fails(snapshot):
    with pytest.raises(ValueError, match="nonnegative"):
        due_disposition(
            scheduled_for=snapshot.scheduled_for,
            now=snapshot.scheduled_for,
            lateness_window=timedelta(seconds=-1),
        )


@pytest.mark.parametrize("tz", [None, timezone(timedelta(hours=-4))])
def test_snapshot_rejects_naive_and_non_utc_instants(snapshot, tz):
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        replace(snapshot, scheduled_for=snapshot.scheduled_for.replace(tzinfo=tz))


@pytest.mark.parametrize(
    "change", [{"content_revision": 0}, {"schedule_generation": 0}]
)
def test_snapshot_versions_are_positive(snapshot, change):
    with pytest.raises(ValueError, match="must be positive"):
        replace(snapshot, **change)


@pytest.mark.parametrize(
    ("authoring", "execution", "receiver"), list(product([False, True], repeat=3))
)
def test_execution_requires_flag_and_receiver_independently_of_authoring(
    authoring, execution, receiver
):
    controls = SchedulingFeatureControls(
        authoring_enabled=authoring,
        execution_enabled=execution,
        delivery_receiver_configured=receiver,
    )
    assert controls.can_execute == (execution and receiver)
    assert not SchedulingFeatureControls().can_execute


def test_receipt_is_bound_to_job_workspace_and_payload(snapshot):
    request = DeliveryAcceptanceRequest(
        snapshot=snapshot,
        job_id=uuid4(),
        destination_id=uuid4(),
        artist_profile_id=None,
        authoring_timezone="America/Los_Angeles",
        payload_schema_version=1,
        canonical_payload=b'{"caption":"Approved caption"}',
        payload_fingerprint="a" * 64,
    )
    receipt = DeliveryAcceptanceReceipt(
        delivery_request_id=uuid4(),
        idempotency_key=request.idempotency_key,
        payload_fingerprint=request.payload_fingerprint,
    )
    assert receipt.matches(request)
    assert not receipt.matches(replace(request, job_id=uuid4()))
    assert not receipt.matches(
        replace(request, snapshot=replace(snapshot, workspace_id=uuid4()))
    )
    assert not receipt.matches(replace(request, payload_fingerprint="b" * 64))
    assert not replace(receipt, payload_fingerprint="").matches(
        replace(request, payload_fingerprint="")
    )
    # Fingerprint generation and transactional durability are adapter obligations;
    # constructing a matching receipt alone must never authorize a handoff.
