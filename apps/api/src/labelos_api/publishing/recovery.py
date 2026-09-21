"""Product resolution of failed delivery; never provider success evidence."""

from labelos_database.models import Publication, PublicationAction
from sqlalchemy import and_, exists, or_, select

from labelos_api.publishing.retries import MAX_ATTEMPTS, MAX_ELAPSED


def latest_action(row):
    return row.actions[-1] if row.actions else None


def manual_reserved(row):
    action = latest_action(row)
    return action is not None and action.operation in (
        "begin_manual",
        "complete_manual",
    )


def recovery_granted(row, now):
    action = latest_action(row)
    return bool(
        action
        and action.operation == "authorize_retry"
        and action.publication_version == row.transition_version
        and action.retry_until > now
    )


def budget_available(row, now):
    return budget_available_from_facts(
        len(row.attempts), row.attempts[0].started_at if row.attempts else None, now
    )


def budget_available_from_facts(attempt_count, started_at, now):
    return bool(
        attempt_count
        and attempt_count < MAX_ATTEMPTS
        and started_at is not None
        and now < started_at + MAX_ELAPSED
    )


def resolution(row, now):
    return resolution_from_facts(
        status=row.status,
        retry_disposition=row.retry_disposition,
        next_retry_at=row.next_retry_at,
        transition_version=row.transition_version,
        action=latest_action(row),
        budget=(
            budget_available(row, now)
            if row.status == "retryable_failure" and not manual_reserved(row)
            else False
        ),
        now=now,
    )


def resolution_from_facts(
    *, status, retry_disposition, next_retry_at, transition_version, action, budget, now
):
    if action and action.operation == "complete_manual":
        return "manually_completed"
    if action and action.operation == "begin_manual":
        return "manual_publishing"
    if status == "manual_action_required":
        return "reconciliation_required"
    if status == "permanent_failure":
        return "terminal_failure"
    if status == "retryable_failure":
        if not budget or retry_disposition == "exhausted":
            return "retry_exhausted"
        if (
            action
            and action.operation == "authorize_retry"
            and action.publication_version == transition_version
            and action.retry_until > now
        ):
            return "retry_authorized"
        return {
            "blocked_reconnection": "reconnect_required",
            "manual_action": "human_intervention_required",
        }.get(
            retry_disposition,
            "retry_scheduled" if next_retry_at else "human_intervention_required",
        )
    return status


def action_filters(now):
    """Correlated selectors shared by worker claims and bounded retry sweeps."""
    latest = (
        select(PublicationAction.operation)
        .where(PublicationAction.publication_id == Publication.id)
        .order_by(PublicationAction.version.desc())
        .limit(1)
        .correlate(Publication)
        .scalar_subquery()
    )
    available = or_(latest.is_(None), latest == "authorize_retry")
    grant = exists().where(
        PublicationAction.publication_id == Publication.id,
        PublicationAction.publication_version == Publication.transition_version,
        PublicationAction.operation == "authorize_retry",
        PublicationAction.retry_until > now,
    )
    automatic = and_(
        Publication.retry_disposition.in_(("automatic", "provider_delay")),
        Publication.retry_policy_version == 1,
        Publication.next_retry_at <= now,
        Publication.retry_deadline_at > now,
    )
    return available, or_(automatic, grant)
