"""Pure Publishing Delivery values and validated, append-only lifecycle history.

Like scheduling.contracts, these are trusted internal values, not API input or
authorization. Provider evidence must be established by a future adapter/service.
No value here proves durability, grants execution authority or coordinates work.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID


class PublicationState(StrEnum):
    pending = "pending"
    processing = "processing"
    published = "published"
    retryable_failure = "retryable_failure"
    retrying = "retrying"
    permanent_failure = "permanent_failure"
    manual_action_required = "manual_action_required"
    cancelled = "cancelled"


class PublicationOperation(StrEnum):
    start = "start"
    retry = "retry"
    confirm_success = "confirm_success"
    fail_retryable = "fail_retryable"
    fail_permanently = "fail_permanently"
    require_manual_action = "require_manual_action"
    cancel = "cancel"


TERMINAL_STATES = frozenset(
    {
        PublicationState.published,
        PublicationState.permanent_failure,
        PublicationState.cancelled,
    }
)
_EXECUTING = frozenset({PublicationState.processing, PublicationState.retrying})


class PublicationInvariantError(ValueError):
    """Invalid identity, scope, history or provider evidence."""


class PublicationInvalidTransitionError(PublicationInvariantError):
    """An operation is not legal in the current publication state."""


def transition_target(
    state: PublicationState, operation: PublicationOperation
) -> PublicationState:
    """Validate the graph only; use Publication.transition for evidence guards."""
    if not isinstance(state, PublicationState) or not isinstance(
        operation, PublicationOperation
    ):
        raise PublicationInvalidTransitionError(
            "Invalid publication state or operation"
        )
    resolvable = _EXECUTING | {PublicationState.manual_action_required}
    rules = {
        PublicationOperation.start: (
            {PublicationState.pending},
            PublicationState.processing,
        ),
        PublicationOperation.retry: (
            {PublicationState.retryable_failure},
            PublicationState.retrying,
        ),
        PublicationOperation.confirm_success: (resolvable, PublicationState.published),
        PublicationOperation.fail_retryable: (
            resolvable,
            PublicationState.retryable_failure,
        ),
        PublicationOperation.fail_permanently: (
            resolvable,
            PublicationState.permanent_failure,
        ),
        PublicationOperation.require_manual_action: (
            _EXECUTING,
            PublicationState.manual_action_required,
        ),
        PublicationOperation.cancel: (
            {PublicationState.pending, PublicationState.retryable_failure},
            PublicationState.cancelled,
        ),
    }
    sources, target = rules[operation]
    if state not in sources:
        raise PublicationInvalidTransitionError("Illegal publication transition")
    return target


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise PublicationInvariantError("A nonzero UUID is required")


def _utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise PublicationInvariantError(
            "Publication instants must be timezone-aware UTC"
        )


def _positive(value: int) -> None:
    if type(value) is not int or value < 1:
        raise PublicationInvariantError("A positive integer is required")


@dataclass(frozen=True, kw_only=True)
class PublicationIntent:
    """One immutable target and approved revision from an accepted scheduling job.

    The future inbox retains the existing complete canonical handoff envelope.
    Its workspace/job key deduplicates acceptance; retries reuse this intent and
    publication ID. No schedule planning, provider metadata or credentials live here.
    """

    workspace_id: UUID
    scheduling_job_id: UUID
    content_item_id: UUID
    channel_id: UUID
    destination_id: UUID
    approval_request_id: UUID
    content_revision: int
    schedule_generation: int
    payload_fingerprint: str

    def __post_init__(self) -> None:
        for identifier in (
            self.workspace_id,
            self.scheduling_job_id,
            self.content_item_id,
            self.channel_id,
            self.destination_id,
            self.approval_request_id,
        ):
            _uuid(identifier)
        _positive(self.content_revision)
        _positive(self.schedule_generation)
        if (
            not isinstance(self.payload_fingerprint, str)
            or len(self.payload_fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in self.payload_fingerprint)
        ):
            raise PublicationInvariantError(
                "A canonical SHA-256 fingerprint is required"
            )


@dataclass(frozen=True, kw_only=True)
class PublicationAttempt:
    """Immutable execution start record, persisted before any future external I/O.

    Results are appended as PublicationTransition evidence, never written over
    this record. A reconciliation observation is not a new delivery attempt.
    """

    id: UUID
    workspace_id: UUID
    publication_id: UUID
    number: int
    started_at: datetime

    def __post_init__(self) -> None:
        for identifier in (self.id, self.workspace_id, self.publication_id):
            _uuid(identifier)
        _positive(self.number)
        _utc(self.started_at)


class DeliveryOutcome(StrEnum):
    published = "published"
    # Both failure classifications assert authoritative absence of a side effect.
    retryable_failure = "retryable_failure"
    permanent_failure = "permanent_failure"
    unknown = "unknown"


class EvidenceSource(StrEnum):
    provider_response = "provider_response"
    reconciliation = "reconciliation"
    execution_interrupted = "execution_interrupted"


class PublicationFailureReason(StrEnum):
    temporary_unavailability = "temporary_unavailability"
    rate_limited = "rate_limited"
    invalid_content = "invalid_content"
    destination_unavailable = "destination_unavailable"
    authorization_required = "authorization_required"
    outcome_unknown = "outcome_unknown"


@dataclass(frozen=True, kw_only=True)
class PublicationEvidence:
    """Normalized trusted observation, never a raw response or exception string.

    published means confirmed external publication, not an async acceptance/202.
    A timeout, lost response or uncertain provider job maps to unknown. Only a
    provider response/reconciliation can assert success or definite nonpublication.
    External IDs must be sanitized non-secret identifiers supplied by the adapter.
    """

    workspace_id: UUID
    publication_id: UUID
    attempt_id: UUID
    destination_id: UUID
    outcome: DeliveryOutcome
    source: EvidenceSource
    observed_at: datetime
    external_post_id: str | None = field(default=None, repr=False)
    reason: PublicationFailureReason | None = None

    def __post_init__(self) -> None:
        for identifier in (
            self.workspace_id,
            self.publication_id,
            self.attempt_id,
            self.destination_id,
        ):
            _uuid(identifier)
        _utc(self.observed_at)
        if not isinstance(self.outcome, DeliveryOutcome) or not isinstance(
            self.source, EvidenceSource
        ):
            raise PublicationInvariantError("Invalid evidence classification")
        if (
            self.source == EvidenceSource.execution_interrupted
            and self.outcome != DeliveryOutcome.unknown
        ):
            raise PublicationInvariantError(
                "Interrupted execution has an unknown outcome"
            )
        if self.outcome == DeliveryOutcome.published:
            if (
                not isinstance(self.external_post_id, str)
                or not self.external_post_id.strip()
                or len(self.external_post_id) > 512
                or any(ord(c) < 32 or ord(c) == 127 for c in self.external_post_id)
                or self.reason is not None
            ):
                raise PublicationInvariantError(
                    "Success requires an external post ID and no failure reason"
                )
        else:
            if self.external_post_id is not None or not isinstance(
                self.reason, PublicationFailureReason
            ):
                raise PublicationInvariantError(
                    "Failure requires a safe reason and no external post ID"
                )
            if (self.outcome == DeliveryOutcome.unknown) != (
                self.reason == PublicationFailureReason.outcome_unknown
            ):
                raise PublicationInvariantError(
                    "Unknown outcomes require reconciliation"
                )


_OUTCOME_OPERATION = {
    DeliveryOutcome.published: PublicationOperation.confirm_success,
    DeliveryOutcome.retryable_failure: PublicationOperation.fail_retryable,
    DeliveryOutcome.permanent_failure: PublicationOperation.fail_permanently,
    DeliveryOutcome.unknown: PublicationOperation.require_manual_action,
}


@dataclass(frozen=True, kw_only=True)
class PublicationTransition:
    """Append-only lifecycle fact, with either an attempt start or an observation."""

    operation: PublicationOperation
    occurred_at: datetime
    attempt: PublicationAttempt | None = None
    evidence: PublicationEvidence | None = None

    def __post_init__(self) -> None:
        _utc(self.occurred_at)
        if not isinstance(self.operation, PublicationOperation):
            raise PublicationInvariantError("Invalid publication operation")
        if self.operation in {PublicationOperation.start, PublicationOperation.retry}:
            valid = (
                isinstance(self.attempt, PublicationAttempt) and self.evidence is None
            )
        elif self.operation == PublicationOperation.cancel:
            valid = self.attempt is None and self.evidence is None
        else:
            valid = (
                self.attempt is None
                and isinstance(self.evidence, PublicationEvidence)
                and _OUTCOME_OPERATION[self.evidence.outcome] == self.operation
            )
        if not valid:
            raise PublicationInvariantError(
                "Operation requires matching attempt or evidence"
            )


@dataclass(frozen=True, kw_only=True)
class Publication:
    """Immutable aggregate; state is validated from its ordered execution history.

    The journal mirrors Scheduling's transition history convention. This in-memory
    representation is not a persistence framework. Stage 2 must atomically persist
    the state projection, new attempts and new transitions with concurrency checks.
    """

    id: UUID
    intent: PublicationIntent
    created_at: datetime
    history: tuple[PublicationTransition, ...] = ()
    state: PublicationState = field(init=False, default=PublicationState.pending)

    def __post_init__(self) -> None:
        _uuid(self.id)
        _utc(self.created_at)
        if (
            not isinstance(self.intent, PublicationIntent)
            or type(self.history) is not tuple
        ):
            raise PublicationInvariantError("Immutable intent and history are required")
        state = PublicationState.pending
        previous_at = self.created_at
        attempts: list[PublicationAttempt] = []
        for entry in self.history:
            if not isinstance(entry, PublicationTransition):
                raise PublicationInvariantError("Invalid publication history entry")
            target = transition_target(state, entry.operation)
            if entry.occurred_at < previous_at:
                raise PublicationInvariantError(
                    "Publication history must be chronological"
                )
            if entry.attempt is not None:
                attempt = entry.attempt
                if (
                    attempt.workspace_id != self.workspace_id
                    or attempt.publication_id != self.id
                    or attempt.number != len(attempts) + 1
                    or attempt.started_at != entry.occurred_at
                    or any(previous.id == attempt.id for previous in attempts)
                ):
                    raise PublicationInvariantError(
                        "Attempt scope, sequence or identity mismatch"
                    )
                attempts.append(attempt)
            if entry.evidence is not None:
                evidence = entry.evidence
                if (
                    not attempts
                    or evidence.workspace_id != self.workspace_id
                    or evidence.publication_id != self.id
                    or evidence.destination_id != self.intent.destination_id
                    or evidence.attempt_id != attempts[-1].id
                    or not previous_at <= evidence.observed_at <= entry.occurred_at
                ):
                    raise PublicationInvariantError(
                        "Evidence scope, attempt or timestamp mismatch"
                    )
                if (
                    state == PublicationState.manual_action_required
                    and evidence.source != EvidenceSource.reconciliation
                ):
                    raise PublicationInvariantError(
                        "Manual action requires authoritative reconciliation"
                    )
            previous_at = entry.occurred_at
            state = target
        object.__setattr__(self, "state", state)

    @property
    def workspace_id(self) -> UUID:
        return self.intent.workspace_id

    @property
    def attempts(self) -> tuple[PublicationAttempt, ...]:
        return tuple(
            entry.attempt for entry in self.history if entry.attempt is not None
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def transition(
        self, *, workspace_id: UUID, entry: PublicationTransition
    ) -> "Publication":
        """Append one fact; caller supplies authenticated scope, never user JSON.

        Cancellation is a delivery response to Scheduling's cancellation command,
        allowed only while no side effect is possible. It cannot undo publication.
        """
        _uuid(workspace_id)
        if workspace_id != self.workspace_id:
            raise PublicationInvariantError("Publication workspace mismatch")
        return replace(self, history=(*self.history, entry))
