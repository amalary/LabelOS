"""Prepared content bytes. No URLs, filesystem paths or provider credentials."""

import hashlib
import re

from labelos_database.capabilities import Capability
from labelos_database.models import MarketingContentItem, MarketingMediaAsset
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import lazyload

from labelos_api.scheduling.payload import (
    MAX_ASSET_BYTES,
    MAX_PAYLOAD_BYTES,
    InvalidHandoffPayload,
)
from labelos_api.services import marketing_content_service as content

MEDIA_TYPE = re.compile(r"(?:image|video|audio)/[a-z0-9][a-z0-9.+-]{0,63}")
DIGEST = re.compile(r"[0-9a-f]{64}")


async def authorize_upload(session, workspace_id, item_id, actor, *, lock=False):
    await content._require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_content_edit,
    )
    statement = (
        select(MarketingContentItem)
        .options(lazyload("*"))
        .where(
            MarketingContentItem.organization_id == workspace_id,
            MarketingContentItem.id == item_id,
        )
    )
    if lock:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise content.MarketingContentNotFoundError("Not found")
    await content._require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_content_edit,
        campaign_id=item.campaign_id,
    )
    return item


async def store_asset(session, workspace_id, item_id, actor, data, media_type):
    # Serialize uploads to this content and recheck authorization after body I/O.
    await authorize_upload(session, workspace_id, item_id, actor, lock=True)
    if not MEDIA_TYPE.fullmatch(media_type) or not 0 < len(data) <= MAX_ASSET_BYTES:
        raise InvalidHandoffPayload()
    digest = hashlib.sha256(data).hexdigest()
    reference = {"sha256": digest, "size_bytes": len(data), "media_type": media_type}
    existing = await session.get(MarketingMediaAsset, (workspace_id, item_id, digest))
    if existing is not None:
        if (existing.media_type, existing.size_bytes, existing.data) != (
            media_type,
            len(data),
            data,
        ):
            raise InvalidHandoffPayload()
        return reference
    session.add(
        MarketingMediaAsset(
            workspace_id=workspace_id,
            content_item_id=item_id,
            data=data,
            **reference,
        )
    )
    await session.flush()
    return reference


async def load_approved_assets(session, workspace_id, item, channel):
    """Called under Scheduling's source locks; references remain approval-owned.

    Bound the query before loading bytes, then verify every approved digest,
    length and media type. A hash alone never grants cross-content access.
    """
    refs = channel.asset_refs or item.asset_refs or []
    if not isinstance(refs, list) or len(refs) > 32:
        raise InvalidHandoffPayload()
    if not refs:
        return {}
    total = 0
    for ref in refs:
        if (
            not isinstance(ref, dict)
            or set(ref) != {"sha256", "size_bytes", "media_type"}
            or not isinstance(ref["sha256"], str)
            or not DIGEST.fullmatch(ref["sha256"])
            or type(ref["size_bytes"]) is not int
            or not 0 < ref["size_bytes"] <= MAX_ASSET_BYTES
            or not isinstance(ref["media_type"], str)
            or not MEDIA_TYPE.fullmatch(ref["media_type"])
        ):
            raise InvalidHandoffPayload()
        total += ref["size_bytes"]
    if total > MAX_PAYLOAD_BYTES * 3 // 4:
        raise InvalidHandoffPayload()
    rows = await session.scalars(
        select(MarketingMediaAsset).where(
            MarketingMediaAsset.workspace_id == workspace_id,
            MarketingMediaAsset.content_item_id == item.id,
            # Match metadata in SQL so a forged tiny size cannot load a large blob.
            or_(
                *(
                    and_(
                        MarketingMediaAsset.sha256 == ref["sha256"],
                        MarketingMediaAsset.size_bytes == ref["size_bytes"],
                        MarketingMediaAsset.media_type == ref["media_type"],
                    )
                    for ref in refs
                )
            ),
        )
    )
    assets = {row.sha256: row for row in rows}
    for ref in refs:
        row = assets.get(ref["sha256"])
        if (
            row is None
            or row.media_type != ref["media_type"]
            or len(row.data) != ref["size_bytes"]
            or hashlib.sha256(row.data).hexdigest() != ref["sha256"]
        ):
            raise InvalidHandoffPayload()
    return {digest: row.data for digest, row in assets.items()}
