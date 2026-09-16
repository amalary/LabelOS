"""Pure contracts for docs/development/scheduling-engine-contract.md.

These values do not authenticate callers, load authoritative evidence, coordinate
transactions, or prove durability. Future adapters must meet those obligations.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from labelos_database.models import ApprovalRequestStatus, MarketingContentItemStatus
from sqlalchemy.ext.asyncio import AsyncSession


class SchedulingJobState(StrEnum):
    pending = "pending"
    claimed = "claimed"
    handed_off = "handed_off"
    blocked = "blocked"
    cancelled = "cancelled"
    superseded = "superseded"


class SchedulingOperation(StrEnum):
    activate = "activate"
    claim = "claim"
    accept_delivery = "accept_delivery"
    block = "block"
    cancel = "cancel"
    supersede = "supersede"
    revalidate = "revalidate"
    recover_claim = "recover_claim"


def transition_target(
    state: SchedulingJobState | None, operation: SchedulingOperation
) -> SchedulingJobState:
    """Check graph only; authority, locking and eligibility guards are external."""
    rules = {
        SchedulingOperation.activate: ({None}, SchedulingJobState.pending),
        SchedulingOperation.claim: (
            {SchedulingJobState.pending},
            SchedulingJobState.claimed,
        ),
        SchedulingOperation.accept_delivery: (
            {SchedulingJobState.claimed},
            SchedulingJobState.handed_off,
        ),
        SchedulingOperation.block: (
            {SchedulingJobState.pending, SchedulingJobState.claimed},
            SchedulingJobState.blocked,
        ),
        SchedulingOperation.cancel: (
            {
                SchedulingJobState.pending,
                SchedulingJobState.claimed,
                SchedulingJobState.blocked,
            },
            SchedulingJobState.cancelled,
        ),
        SchedulingOperation.supersede: (
            {
                SchedulingJobState.pending,
                SchedulingJobState.claimed,
                SchedulingJobState.blocked,
            },
            SchedulingJobState.superseded,
        ),
        SchedulingOperation.revalidate: (
            {SchedulingJobState.blocked},
            SchedulingJobState.pending,
        ),
        SchedulingOperation.recover_claim: (
            {SchedulingJobState.claimed},
            SchedulingJobState.pending,
        ),
    }
    sources, target = rules[operation]
    if state not in sources:
        raise ValueError(f"Illegal scheduling transition: {state} / {operation}")
    return target


class SchedulingBlockedReason(StrEnum):
    connection_unavailable = "connection_unavailable"
    reconnect_required = "reconnect_required"
    capability_unavailable = "capability_unavailable"
    destination_mismatch = "destination_mismatch"
    manual_delivery_required = "manual_delivery_required"
    stale_content_revision = "stale_content_revision"
    stale_approval = "stale_approval"
    changed_schedule_generation = "changed_schedule_generation"
    missing_durable_delivery_receiver = "missing_durable_delivery_receiver"
    missed_schedule_window = "missed_schedule_window"
    ineligible_parent_state = "ineligible_parent_state"
    missing_schedule_intent = "missing_schedule_intent"
    handoff_contract_violation = "handoff_contract_violation"


@dataclass(frozen=True, kw_only=True)
class ApprovalEvidence:
    """Repository-derived approval evidence read inside the locked transaction."""

    request_id: UUID
    workspace_id: UUID
    resource_type: str
    content_item_id: UUID
    content_revision: int
    status: ApprovalRequestStatus
    invalidated: bool


@dataclass(frozen=True, kw_only=True)
class ScheduleSnapshot:
    """Server-derived immutable snapshot; never a second authoring API."""

    workspace_id: UUID
    content_item_id: UUID
    channel_id: UUID
    content_revision: int
    approval_request_id: UUID
    schedule_generation: int
    scheduled_for: datetime

    def __post_init__(self) -> None:
        _require_utc(self.scheduled_for)
        if self.content_revision < 1 or self.schedule_generation < 1:
            raise ValueError("Revision and generation must be positive")


def approval_blocked_reason(
    snapshot: ScheduleSnapshot,
    *,
    current_revision: int,
    approved_revision: int | None,
    parent_status: MarketingContentItemStatus,
    evidence: ApprovalEvidence | None,
) -> SchedulingBlockedReason | None:
    """Revision/approval subset of eligibility; does not grant execution authority."""
    if snapshot.content_revision != current_revision:
        return SchedulingBlockedReason.stale_content_revision
    if (
        approved_revision != current_revision
        or evidence is None
        or evidence.request_id != snapshot.approval_request_id
        or evidence.workspace_id != snapshot.workspace_id
        or evidence.resource_type != "marketing_content_item"
        or evidence.content_item_id != snapshot.content_item_id
        or evidence.content_revision != current_revision
        or evidence.status != ApprovalRequestStatus.approved
        or evidence.invalidated
    ):
        return SchedulingBlockedReason.stale_approval
    if parent_status not in {
        MarketingContentItemStatus.approved,
        MarketingContentItemStatus.scheduled,
    }:
        return SchedulingBlockedReason.ineligible_parent_state
    return None


def schedule_blocked_reason(
    snapshot: ScheduleSnapshot,
    *,
    scheduled_at: datetime | None,
    schedule_generation: int,
) -> SchedulingBlockedReason | None:
    if scheduled_at is None:
        return SchedulingBlockedReason.missing_schedule_intent
    _require_utc(scheduled_at)
    if (
        schedule_generation != snapshot.schedule_generation
        or scheduled_at != snapshot.scheduled_for
    ):
        return SchedulingBlockedReason.changed_schedule_generation
    return None


class DueDisposition(StrEnum):
    future = "future"
    claimable = "claimable"
    missed = "missed"


def due_disposition(
    *, scheduled_for: datetime, now: datetime, lateness_window: timedelta
) -> DueDisposition:
    """Inclusive catch-up boundary using caller-supplied config and database time."""
    _require_utc(scheduled_for)
    _require_utc(now)
    if lateness_window < timedelta(0):
        raise ValueError("Lateness window must be nonnegative")
    age = now - scheduled_for
    if age < timedelta(0):
        return DueDisposition.future
    if age <= lateness_window:
        return DueDisposition.claimable
    return DueDisposition.missed


def _require_utc(value: datetime) -> None:
    if value.utcoffset() != timedelta(0):
        raise ValueError("Scheduling instants must be timezone-aware UTC")


@dataclass(frozen=True, kw_only=True)
class SchedulingFeatureControls:
    authoring_enabled: bool = False
    execution_enabled: bool = False
    delivery_receiver_configured: bool = False

    @property
    def can_execute(self) -> bool:
        # Authoring gates user mutations independently from draining existing jobs.
        return self.execution_enabled and self.delivery_receiver_configured


@dataclass(frozen=True, kw_only=True)
class DeliveryAcceptanceRequest:
    snapshot: ScheduleSnapshot
    job_id: UUID
    destination_id: UUID
    artist_profile_id: UUID | None
    authoring_timezone: str
    payload_fingerprint: str
    payload_schema_version: int
    canonical_payload: bytes = field(repr=False)
    execution_mode: str = "automatic"
    correlation_id: UUID | None = None

    @property
    def idempotency_key(self) -> str:
        return f"labelos:scheduling:v1:{self.snapshot.workspace_id}:{self.job_id}"


@dataclass(frozen=True, kw_only=True)
class DeliveryAcceptanceReceipt:
    """Valid only from a trusted transactional receiver; durable at outer commit."""

    delivery_request_id: UUID
    idempotency_key: str
    payload_fingerprint: str

    def matches(self, request: DeliveryAcceptanceRequest) -> bool:
        return (
            bool(self.payload_fingerprint)
            and self.idempotency_key == request.idempotency_key
            and self.payload_fingerprint == request.payload_fingerprint
        )


class DurableDeliveryReceiverUnavailable(RuntimeError):
    """Legacy unavailable signal, translated to RetryableUnavailable by composition."""


@dataclass(frozen=True, kw_only=True)
class DurableAccepted:
    """Staged in the caller's transaction; durable only after its commit."""

    receipt: DeliveryAcceptanceReceipt

    @property
    def receipt_id(self) -> UUID:
        return self.receipt.delivery_request_id


@dataclass(frozen=True)
class RetryableUnavailable:
    # No free-form provider errors or exception messages cross this boundary.
    reason_code: str = field(default="delivery_unavailable", init=False)


@dataclass(frozen=True)
class TerminalRejected:
    reason_code: str = field(default="handoff_rejected", init=False)


DeliveryAcceptanceResult = DurableAccepted | RetryableUnavailable | TerminalRejected


class PublishingDeliveryAcceptancePort(Protocol):
    async def accept(
        self, session: AsyncSession, request: DeliveryAcceptanceRequest
    ) -> DeliveryAcceptanceResult:
        """Insert/deduplicate a delivery-owned inbox in the caller's transaction.

        No internal commit, external I/O, credentials, or provider calls. Persist
        the complete immutable payload before returning a matching receipt. The
        receipt and handed_off transition become durable together at outer commit.
        Same key/different fingerprint returns TerminalRejected, never overwrites.
        Nonacceptance results must leave no inbox writes. Unknown commit outcomes
        are exceptions requiring durable readback, never RetryableUnavailable.
        """
        ...
