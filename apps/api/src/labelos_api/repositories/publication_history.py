"""Bounded history facts. All selects are scalar allowlists, never ORM graphs."""

from labelos_database.models import (
    Publication,
    PublicationAction,
    PublicationAttempt,
    PublicationListMetadata,
    PublicationTransition,
    SchedulingJob,
    SocialAccountConnection,
)
from labelos_database.publishing import REASONS
from sqlalchemy import and_, exists, func, select


async def list_metadata(
    session, workspace_id, content_item_id, *, limit, after_id=None
):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid_history_page_size")
    p, a, t = Publication, PublicationAction, PublicationTransition
    query = select(
        p.id,
        p.workspace_id,
        p.marketing_content_item_id.label("content_item_id"),
        p.provider,
        p.social_account_connection_id.label("destination_id"),
        p.destination_identity,
        p.status.label("delivery_status"),
        p.published_at,
        p.external_post_id,
        p.provider_url,
        p.transition_version,
        p.failure_category,
        p.retry_disposition,
        p.next_retry_at,
        p.authorized_content_revision.label("content_revision"),
        p.scheduling_job_id,
    ).where(
        p.workspace_id == workspace_id, p.marketing_content_item_id == content_item_id
    )
    if after_id is not None:
        query = query.where(p.id > after_id)
    # Bound before any journal work or joins; the extra row is only a cursor probe.
    page = query.order_by(p.id).limit(limit + 1).cte("history_page")

    def scoped(model):
        return and_(
            model.workspace_id == workspace_id, model.publication_id == page.c.id
        )

    def latest_id(model, *conditions):
        return (
            select(model.id)
            .where(scoped(model), *conditions)
            .order_by(model.version.desc())
            .limit(1)
            .correlate(page)
            .scalar_subquery()
        )

    attempt_count = (
        select(func.count())
        .select_from(PublicationAttempt)
        .where(scoped(PublicationAttempt))
        .correlate(page)
        .scalar_subquery()
    )
    first_start = (
        select(PublicationAttempt.started_at)
        .where(scoped(PublicationAttempt))
        .order_by(PublicationAttempt.number)
        .limit(1)
        .correlate(page)
        .scalar_subquery()
    )
    authorized = (
        exists()
        .where(
            scoped(a),
            a.operation == "authorize_retry",
            a.publication_version == page.c.transition_version,
        )
        .correlate(page)
    )
    m, j, d = PublicationListMetadata, SchedulingJob, SocialAccountConnection
    rows = await session.execute(
        select(
            page,
            m.channel,
            m.placement,
            j.scheduled_for,
            j.schedule_timezone.label("authoring_timezone"),
            d.id.label("connection_id"),
            d.external_account_id,
            d.username,
            d.display_name,
            attempt_count.label("attempt_count"),
            first_start.label("started_at"),
            authorized.label("retry_authorized_for_version"),
            a.version.label("action_version"),
            a.operation,
            a.publication_version,
            a.retry_until,
            a.occurred_at.label("action_at"),
            a.external_post_id.label("manual_external_post_id"),
            a.provider_url.label("manual_provider_url"),
            t.failure_reason.label("latest_failure_reason"),
            t.observed_at.label("last_failed_at"),
        )
        .select_from(page)
        .join(m, and_(m.publication_id == page.c.id, m.workspace_id == workspace_id))
        .join(j, and_(j.id == page.c.scheduling_job_id, j.workspace_id == workspace_id))
        .outerjoin(
            d, and_(d.id == page.c.destination_id, d.organization_id == workspace_id)
        )
        .outerjoin(a, and_(a.id == latest_id(a), a.workspace_id == workspace_id))
        .outerjoin(
            t,
            and_(
                t.id == latest_id(t, t.failure_reason.in_(REASONS)),
                t.workspace_id == workspace_id,
            ),
        )
        .order_by(page.c.id)
    )
    return rows.all()
