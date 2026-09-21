"""Content-scoped authorization once per history page, then metadata only."""

import hashlib
from datetime import UTC, datetime

from labelos_database.capabilities import Capability
from labelos_database.models import MarketingContentItem
from sqlalchemy import select

from labelos_api.publishing.recovery import (
    budget_available_from_facts,
    resolution_from_facts,
)
from labelos_api.repositories.publication_history import list_metadata
from labelos_api.scheduling.payload import canonical_json
from labelos_api.services import marketing_content_service as content
from labelos_api.services.publication_recovery import PublicationHumanRequired


async def list_publications(
    session, workspace_id, content_item_id, actor, *, limit=100, after_id=None
):
    if actor is None:
        raise PublicationHumanRequired("authenticated_actor_required")
    if not 1 <= limit <= 100:
        raise ValueError("invalid_history_page_size")

    async def require(capability, campaign_id=None):
        await content._require_capability(
            session,
            actor=actor,
            workspace_id=workspace_id,
            capability=capability,
            campaign_id=campaign_id,
        )

    await require(Capability.marketing_content_view)
    # Authorization needs only the current campaign ID, not content, channels,
    # artist relationships, JSON metadata or asset references.
    item = (
        await session.execute(
            select(MarketingContentItem.campaign_id).where(
                MarketingContentItem.organization_id == workspace_id,
                MarketingContentItem.id == content_item_id,
            )
        )
    ).one_or_none()
    if item is None:
        raise content.MarketingContentNotFoundError("Not found")
    await require(Capability.marketing_content_view, item.campaign_id)
    can_manage = False
    if (
        actor is not None
        and content._actor_kind(actor) == "user"
        and content._actor_user(actor) is not None
    ):
        try:
            await require(Capability.marketing_content_schedule)
            await require(Capability.marketing_content_schedule, item.campaign_id)
            can_manage = True
        except content.MarketingContentAuthorizationError:
            pass
    rows = await list_metadata(
        session, workspace_id, content_item_id, limit=limit, after_id=after_id
    )
    now = datetime.now(UTC)
    publications = []
    for row in rows[:limit]:
        budget = budget_available_from_facts(row.attempt_count, row.started_at, now)
        state = resolution_from_facts(
            status=row.delivery_status,
            retry_disposition=row.retry_disposition,
            next_retry_at=row.next_retry_at,
            transition_version=row.transition_version,
            action=row if row.operation else None,
            budget=budget,
            now=now,
        )
        reserved = row.operation in ("begin_manual", "complete_manual")
        completed = state == "manually_completed"
        matches = bool(
            row.connection_id is not None
            and hashlib.sha256(
                canonical_json([row.provider, row.external_account_id])
            ).hexdigest()
            == row.destination_identity
        )
        value = {
            key: getattr(row, key)
            for key in (
                "id",
                "workspace_id",
                "content_item_id",
                "provider",
                "destination_id",
                "delivery_status",
                "published_at",
                "channel",
                "placement",
                "content_revision",
                "scheduled_for",
                "authoring_timezone",
                "attempt_count",
                "started_at",
                "latest_failure_reason",
                "last_failed_at",
                "failure_category",
                "transition_version",
                "next_retry_at",
            )
        }
        value.update(
            scheduled_for=row.scheduled_for.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
            resolution=state,
            destination_identity_matches=matches,
            destination_account=(
                {
                    key: getattr(row, key)
                    for key in ("external_account_id", "username", "display_name")
                }
                if matches
                else None
            ),
            completion_source=(
                "human"
                if completed
                else "provider" if row.delivery_status == "published" else None
            ),
            external_post_id=(
                row.manual_external_post_id if completed else row.external_post_id
            ),
            provider_url=row.manual_provider_url if completed else row.provider_url,
            manual_completed_at=row.action_at if completed else None,
            action_version=row.action_version or 0,
            can_manage_recovery=can_manage,
            can_authorize_retry=row.delivery_status == "retryable_failure"
            and row.retry_disposition in ("blocked_reconnection", "manual_action")
            and budget
            and not reserved
            and not row.retry_authorized_for_version,
            can_begin_manual=row.delivery_status
            in ("retryable_failure", "permanent_failure")
            and not reserved,
            can_complete_manual=state == "manual_publishing",
        )
        publications.append(value)
    return {
        "publications": publications,
        "next_after_id": rows[limit - 1].id if len(rows) > limit else None,
    }
