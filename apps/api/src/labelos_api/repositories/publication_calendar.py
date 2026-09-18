"""Read-only calendar facts owned by Publishing Delivery.

Attempts, manual assertions and legacy Marketing timestamps are not external
success signals. One published Publication yields one fact regardless of retries.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from labelos_database.models import MarketingContentItem, Publication
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, kw_only=True)
class PublishedCalendarFact:
    publication_id: UUID
    workspace_id: UUID
    content_item_id: UUID
    channel_id: UUID
    social_account_connection_id: UUID
    provider: str
    channel: str
    placement: str
    published_at: datetime
    external_post_id: str
    provider_url: str | None


def published_for_item(workspace_id: UUID):
    return select(Publication.id).where(
        Publication.workspace_id == workspace_id,
        Publication.workspace_id == MarketingContentItem.organization_id,
        Publication.marketing_content_item_id == MarketingContentItem.id,
        Publication.status == "published",
    )


async def list_facts(
    session: AsyncSession, workspace_id: UUID, content_item_ids: Sequence[UUID]
) -> list[PublishedCalendarFact]:
    if not content_item_ids:
        return []
    rows = await session.scalars(
        select(Publication)
        .where(
            Publication.workspace_id == workspace_id,
            Publication.marketing_content_item_id.in_(content_item_ids),
            Publication.status == "published",
        )
        .order_by(Publication.published_at, Publication.id)
    )
    facts = []
    for row in rows:
        if row.published_at is None or row.external_post_id is None:
            continue
        # Only expose allowlisted intent metadata, never the envelope/media payload.
        content = json.loads(row.canonical_envelope)["content"]
        facts.append(
            PublishedCalendarFact(
                publication_id=row.id,
                workspace_id=row.workspace_id,
                content_item_id=row.marketing_content_item_id,
                channel_id=row.marketing_content_item_channel_id,
                social_account_connection_id=row.social_account_connection_id,
                provider=row.provider,
                channel=content["channel"],
                placement=content["placement"],
                published_at=row.published_at,
                external_post_id=row.external_post_id,
                provider_url=row.provider_url,
            )
        )
    return facts
