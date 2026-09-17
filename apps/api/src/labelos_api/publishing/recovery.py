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
    return bool(
        row.attempts
        and len(row.attempts) < MAX_ATTEMPTS
        and now < row.attempts[0].started_at + MAX_ELAPSED
    )


def resolution(row, now):
    action = latest_action(row)
    if action and action.operation == "complete_manual":
        return "manually_completed"
    if action and action.operation == "begin_manual":
        return "manual_publishing"
    if row.status == "manual_action_required":
        return "reconciliation_required"
    if row.status == "permanent_failure":
        return "terminal_failure"
    if row.status == "retryable_failure":
        if not budget_available(row, now) or row.retry_disposition == "exhausted":
            return "retry_exhausted"
        if recovery_granted(row, now):
            return "retry_authorized"
        return {
            "blocked_reconnection": "reconnect_required",
            "manual_action": "human_intervention_required",
        }.get(
            row.retry_disposition,
            "retry_scheduled" if row.next_retry_at else "human_intervention_required",
        )
    return row.status


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
