from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from itertools import product
from uuid import UUID, uuid4

import pytest

from labelos_api.publishing.contracts import (
    TERMINAL_STATES,
    DeliveryOutcome,
    EvidenceSource,
    Publication,
    PublicationAttempt,
    PublicationEvidence,
    PublicationIntent,
    PublicationInvariantError,
    PublicationTransition,
    transition_target,
)
from labelos_api.publishing.contracts import (
    PublicationFailureReason as Reason,
)
from labelos_api.publishing.contracts import (
    PublicationOperation as Operation,
)
from labelos_api.publishing.contracts import (
    PublicationState as State,
)

NOW = datetime(2026, 9, 16, tzinfo=UTC)
LEGAL_EDGES = {
    (State.pending, Operation.start): State.processing,
    (State.pending, Operation.cancel): State.cancelled,
    (State.retryable_failure, Operation.retry): State.retrying,
    (State.retryable_failure, Operation.cancel): State.cancelled,
    **{
        (state, operation): target
        for state in (State.processing, State.retrying, State.manual_action_required)
        for operation, target in (
            (Operation.confirm_success, State.published),
            (Operation.fail_retryable, State.retryable_failure),
            (Operation.fail_permanently, State.permanent_failure),
        )
    },
    (State.processing, Operation.require_manual_action): State.manual_action_required,
    (State.retrying, Operation.require_manual_action): State.manual_action_required,
}


@pytest.fixture
def publication():
    return Publication(
        id=uuid4(),
        created_at=NOW,
        intent=PublicationIntent(
            workspace_id=uuid4(),
            scheduling_job_id=uuid4(),
            content_item_id=uuid4(),
            channel_id=uuid4(),
            destination_id=uuid4(),
            approval_request_id=uuid4(),
            content_revision=3,
            schedule_generation=2,
            payload_fingerprint="a" * 64,
        ),
    )


def append(publication, operation, *, attempt=None, evidence=None, at=NOW):
    return publication.transition(
        workspace_id=publication.workspace_id,
        entry=PublicationTransition(
            operation=operation,
            occurred_at=at,
            attempt=attempt,
            evidence=evidence,
        ),
    )


def start(publication, **changes):
    attempt = PublicationAttempt(
        id=uuid4(),
        workspace_id=publication.workspace_id,
        publication_id=publication.id,
        number=len(publication.attempts) + 1,
        started_at=NOW,
    )
    return append(
        publication,
        Operation.start if not publication.attempts else Operation.retry,
        attempt=replace(attempt, **changes),
    )


def evidence_for(publication, outcome=DeliveryOutcome.published, **changes):
    return replace(
        PublicationEvidence(
            workspace_id=publication.workspace_id,
            publication_id=publication.id,
            attempt_id=publication.attempts[-1].id,
            destination_id=publication.intent.destination_id,
            outcome=outcome,
            source=EvidenceSource.provider_response,
            observed_at=NOW,
            external_post_id=(
                "post-123" if outcome == DeliveryOutcome.published else None
            ),
            reason=(
                None
                if outcome == DeliveryOutcome.published
                else (
                    Reason.outcome_unknown
                    if outcome == DeliveryOutcome.unknown
                    else Reason.temporary_unavailability
                )
            ),
        ),
        **changes,
    )


@pytest.mark.parametrize(("state", "operation"), list(product(State, Operation)))
def test_every_state_operation_pair(state, operation):
    expected = LEGAL_EDGES.get((state, operation))
    if expected is None:
        with pytest.raises(PublicationInvariantError):
            transition_target(state, operation)
    else:
        assert transition_target(state, operation) == expected


@pytest.mark.parametrize("value", [None, "pending", "handed_off", "scheduled", 1])
def test_foreign_states_cannot_signal_publishing_success(value):
    with pytest.raises(PublicationInvariantError):
        transition_target(value, Operation.confirm_success)


def test_acceptance_is_pending_not_published(publication):
    assert publication.state == State.pending
    assert not publication.is_terminal
    assert publication.attempts == ()
    with pytest.raises((ValueError, TypeError)):
        replace(publication, state=State.published)


def test_retry_preserves_one_intent_and_all_attempt_history(publication):
    processing = start(publication)
    failed = append(
        processing,
        Operation.fail_retryable,
        evidence=evidence_for(
            processing,
            DeliveryOutcome.retryable_failure,
        ),
    )
    assert failed.state == State.retryable_failure
    assert not failed.is_terminal
    retrying = start(failed)
    assert retrying.state == State.retrying
    published = append(
        retrying, Operation.confirm_success, evidence=evidence_for(retrying)
    )
    assert published.state == State.published and published.is_terminal
    assert published.id == publication.id
    assert published.intent is publication.intent
    assert published.history[: len(failed.history)] == failed.history
    assert published.attempts[0] is processing.attempts[0]
    assert [attempt.number for attempt in published.attempts] == [1, 2]
    assert published.attempts[0].id != published.attempts[1].id
    assert publication.history == ()
    with pytest.raises(FrozenInstanceError):
        published.attempts[0].number = 7
    with pytest.raises(FrozenInstanceError):
        published.intent.destination_id = uuid4()


@pytest.mark.parametrize(
    "outcome,operation,target",
    [
        (DeliveryOutcome.published, Operation.confirm_success, State.published),
        (
            DeliveryOutcome.retryable_failure,
            Operation.fail_retryable,
            State.retryable_failure,
        ),
        (
            DeliveryOutcome.permanent_failure,
            Operation.fail_permanently,
            State.permanent_failure,
        ),
    ],
)
def test_ambiguous_result_requires_reconciliation(
    publication, outcome, operation, target
):
    processing = start(publication)
    unknown = evidence_for(
        processing, DeliveryOutcome.unknown, source=EvidenceSource.execution_interrupted
    )
    manual = append(processing, Operation.require_manual_action, evidence=unknown)
    assert manual.state == State.manual_action_required
    assert not manual.is_terminal
    for unsafe_operation in (Operation.retry, Operation.cancel, Operation.start):
        with pytest.raises(PublicationInvariantError):
            transition_target(manual.state, unsafe_operation)
    with pytest.raises(PublicationInvariantError, match="reconciliation"):
        append(manual, operation, evidence=evidence_for(manual, outcome))
    resolved = append(
        manual,
        operation,
        evidence=evidence_for(
            manual,
            outcome,
            source=EvidenceSource.reconciliation,
        ),
    )
    assert resolved.state == target
    assert resolved.attempts == manual.attempts
    assert resolved.history[-2].evidence is unknown


@pytest.mark.parametrize("failed_first", [False, True])
def test_cancellation_only_when_no_effect_is_possible(publication, failed_first):
    if failed_first:
        publication = start(publication)
        publication = append(
            publication,
            Operation.fail_retryable,
            evidence=evidence_for(
                publication,
                DeliveryOutcome.retryable_failure,
            ),
        )
    cancelled = append(publication, Operation.cancel)
    assert cancelled.state == State.cancelled and cancelled.is_terminal
    assert cancelled.attempts == publication.attempts


def test_terminal_states_are_explicit_and_have_no_outgoing_edges():
    assert {
        State.published,
        State.permanent_failure,
        State.cancelled,
    } == TERMINAL_STATES
    assert all(source not in TERMINAL_STATES for source, _ in LEGAL_EDGES)


@pytest.mark.parametrize(
    "field", ["workspace_id", "publication_id", "destination_id", "attempt_id"]
)
def test_cross_workspace_target_or_attempt_evidence_rejected(publication, field):
    processing = start(publication)
    with pytest.raises(PublicationInvariantError, match="scope"):
        append(
            processing,
            Operation.confirm_success,
            evidence=evidence_for(
                processing,
                **{field: uuid4()},
            ),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"workspace_id": uuid4()},
        {"publication_id": uuid4()},
        {"number": 2},
        {"started_at": NOW - timedelta(seconds=1)},
    ],
)
def test_attempt_binding_and_sequence(publication, changes):
    with pytest.raises(PublicationInvariantError):
        start(publication, **changes)


def test_duplicate_attempt_id_and_stale_completion_rejected(publication):
    first = start(publication)
    failed = append(
        first,
        Operation.fail_retryable,
        evidence=evidence_for(
            first,
            DeliveryOutcome.retryable_failure,
        ),
    )
    with pytest.raises(PublicationInvariantError):
        start(failed, id=first.attempts[0].id)
    second = start(failed)
    with pytest.raises(PublicationInvariantError):
        append(second, Operation.confirm_success, evidence=evidence_for(first))
    with pytest.raises(PublicationInvariantError):
        start(first)


def test_transition_rejects_wrong_caller_workspace(publication):
    with pytest.raises(PublicationInvariantError, match="workspace"):
        publication.transition(
            workspace_id=uuid4(),
            entry=PublicationTransition(
                operation=Operation.cancel,
                occurred_at=NOW,
            ),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"external_post_id": None},
        {"external_post_id": " "},
        {"external_post_id": "x" * 513},
        {"external_post_id": "post\nsecret"},
        {"reason": Reason.rate_limited},
        {"source": EvidenceSource.execution_interrupted},
        {"source": "provider_response"},
        {"outcome": "published"},
    ],
)
def test_success_requires_typed_authoritative_evidence(publication, changes):
    with pytest.raises(PublicationInvariantError):
        evidence_for(start(publication), **changes)


@pytest.mark.parametrize(
    "operation",
    [
        Operation.confirm_success,
        Operation.fail_retryable,
        Operation.fail_permanently,
        Operation.require_manual_action,
    ],
)
def test_outcome_transition_without_evidence_is_rejected(operation):
    with pytest.raises(PublicationInvariantError):
        PublicationTransition(operation=operation, occurred_at=NOW)


@pytest.mark.parametrize(
    "changes",
    [
        {"reason": None},
        {"reason": "raw provider exception: token"},
        {"reason": Reason.outcome_unknown},
        {"external_post_id": "post-123"},
        {"source": EvidenceSource.execution_interrupted},
    ],
)
def test_retry_requires_confirmed_nonpublication(publication, changes):
    with pytest.raises(PublicationInvariantError):
        evidence_for(start(publication), DeliveryOutcome.retryable_failure, **changes)


def test_outcome_cannot_be_reclassified_by_transition(publication):
    processing = start(publication)
    with pytest.raises(PublicationInvariantError):
        append(
            processing,
            Operation.fail_permanently,
            evidence=evidence_for(
                processing,
                DeliveryOutcome.retryable_failure,
            ),
        )


@pytest.mark.parametrize(
    "field",
    [
        "workspace_id",
        "scheduling_job_id",
        "content_item_id",
        "channel_id",
        "destination_id",
        "approval_request_id",
    ],
)
@pytest.mark.parametrize("value", [None, "not-a-uuid", UUID(int=0)])
def test_intent_requires_all_scoped_relationships(publication, field, value):
    with pytest.raises(PublicationInvariantError):
        replace(publication.intent, **{field: value})


@pytest.mark.parametrize("field", ["content_revision", "schedule_generation"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_positive_integer_revision_and_generation(publication, field, value):
    with pytest.raises(PublicationInvariantError):
        replace(publication.intent, **{field: value})


@pytest.mark.parametrize("value", [None, "", "A" * 64, "g" * 64, "a" * 63])
def test_intent_requires_canonical_fingerprint(publication, value):
    with pytest.raises(PublicationInvariantError):
        replace(publication.intent, payload_fingerprint=value)


@pytest.mark.parametrize(
    "value", [NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=1)))]
)
def test_utc_required_for_every_record(publication, value):
    processing = start(publication)
    for record, timestamp in (
        (publication, "created_at"),
        (processing.attempts[0], "started_at"),
        (processing.history[0], "occurred_at"),
        (evidence_for(processing), "observed_at"),
    ):
        with pytest.raises(PublicationInvariantError):
            replace(record, **{timestamp: value})


def test_invalid_rehydrated_history_and_time_are_rejected(publication):
    processing = start(publication)
    with pytest.raises(PublicationInvariantError):
        PublicationTransition(operation="published", occurred_at=NOW)
    with pytest.raises(PublicationInvariantError):
        replace(publication, history=("published",))
    with pytest.raises(PublicationInvariantError):
        replace(processing, history=list(processing.history))
    with pytest.raises(PublicationInvariantError):
        replace(processing, created_at=NOW + timedelta(seconds=1))
    with pytest.raises(PublicationInvariantError):
        append(
            processing,
            Operation.confirm_success,
            evidence=evidence_for(
                processing,
                observed_at=NOW + timedelta(seconds=1),
            ),
        )
    with pytest.raises(PublicationInvariantError):
        replace(
            publication,
            history=(
                PublicationTransition(
                    operation=Operation.confirm_success,
                    occurred_at=NOW,
                    evidence=evidence_for(processing),
                ),
            ),
        )


def test_records_have_no_secret_or_arbitrary_payload_fields(publication):
    forbidden = {
        "credentials",
        "credential_ref",
        "access_token",
        "refresh_token",
        "metadata",
        "provider_metadata",
        "raw_response",
        "error_message",
    }
    for model in (
        Publication,
        PublicationIntent,
        PublicationAttempt,
        PublicationEvidence,
        PublicationTransition,
    ):
        assert not forbidden.intersection(field.name for field in fields(model))
    with pytest.raises(TypeError):
        replace(publication, access_token="secret")
    assert "post-123" not in repr(evidence_for(start(publication)))
