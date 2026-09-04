from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from labelos_database.capabilities import Capability
from labelos_database.models import (
    ApprovalRequest,
    MarketingContentItem,
    MarketingContentItemStatus,
)
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

MARKETING_CONTENT_ITEM_RESOURCE_TYPE = "marketing_content_item"


@dataclass(frozen=True, kw_only=True)
class ApprovalResourceCapabilities:
    view: str
    submit: str
    approve: str
    edit: str


@dataclass(frozen=True, kw_only=True)
class ApprovalResourceChannelSummary:
    channel: str
    placement: str


@dataclass(frozen=True, kw_only=True)
class ApprovalResourceQueueSummary:
    resource_type: str
    resource_id: UUID
    title: str
    status: str
    current_revision: int
    approved_revision: int | None
    campaign_id: UUID | None
    campaign_name: str | None
    artist_id: UUID | None
    artist_name: str | None
    release_id: UUID | None
    release_title: str | None
    channels: tuple[ApprovalResourceChannelSummary, ...]


@dataclass(frozen=True, kw_only=True)
class ApprovalResourceContext:
    campaign_id: UUID | None
    campaign_name: str | None
    artist_id: UUID | None
    artist_name: str | None
    release_id: UUID | None
    release_title: str | None


class ApprovalResourceAdapter(Protocol):
    resource_type: str
    capabilities: ApprovalResourceCapabilities

    async def resolve(
        self,
        session: AsyncSession,
        organization_id: UUID,
        resource_id: UUID,
    ) -> object | None: ...

    def current_revision(self, resource: object) -> int: ...

    def current_status(self, resource: object) -> str: ...

    def context(self, resource: object) -> ApprovalResourceContext: ...

    def channels(
        self, resource: object
    ) -> tuple[ApprovalResourceChannelSummary, ...]: ...

    def is_eligible_for_submission(self, resource: object) -> bool: ...

    def queue_summary(self, resource: object) -> ApprovalResourceQueueSummary: ...

    def approved_revision_is_current(
        self,
        resource: object,
        approval_request: ApprovalRequest,
    ) -> bool: ...

    def queue_filter(
        self,
        *,
        organization_id: UUID,
        campaign_id: UUID | None = None,
        artist_id: UUID | None = None,
    ) -> ColumnElement[bool] | None: ...


class UnsupportedApprovalResourceTypeError(ValueError):
    """Raised when a queue operation references an unregistered resource type."""


class MarketingContentItemApprovalResourceAdapter:
    resource_type = MARKETING_CONTENT_ITEM_RESOURCE_TYPE
    capabilities = ApprovalResourceCapabilities(
        view=Capability.marketing_content_view.value,
        submit=Capability.marketing_content_submit_for_review.value,
        approve=Capability.marketing_content_approve.value,
        edit=Capability.marketing_content_edit.value,
    )

    async def resolve(
        self,
        session: AsyncSession,
        organization_id: UUID,
        resource_id: UUID,
    ) -> MarketingContentItem | None:
        return await session.scalar(
            select(MarketingContentItem)
            .options(
                selectinload(MarketingContentItem.channels),
                selectinload(MarketingContentItem.campaign),
                selectinload(MarketingContentItem.artist),
                selectinload(MarketingContentItem.release),
            )
            .where(MarketingContentItem.organization_id == organization_id)
            .where(MarketingContentItem.id == resource_id)
        )

    def current_revision(self, resource: object) -> int:
        item = self._item(resource)
        return item.content_revision

    def current_status(self, resource: object) -> str:
        item = self._item(resource)
        return item.status.value

    def context(self, resource: object) -> ApprovalResourceContext:
        item = self._item(resource)
        campaign = item.__dict__.get("campaign")
        artist = item.__dict__.get("artist")
        release = item.__dict__.get("release")
        return ApprovalResourceContext(
            campaign_id=item.campaign_id,
            campaign_name=campaign.name if campaign is not None else None,
            artist_id=item.artist_id,
            artist_name=artist.name if artist is not None else None,
            release_id=item.release_id,
            release_title=release.title if release is not None else None,
        )

    def channels(self, resource: object) -> tuple[ApprovalResourceChannelSummary, ...]:
        item = self._item(resource)
        return tuple(
            ApprovalResourceChannelSummary(
                channel=channel.channel,
                placement=channel.placement,
            )
            for channel in item.channels
        )

    def is_eligible_for_submission(self, resource: object) -> bool:
        item = self._item(resource)
        return item.status == MarketingContentItemStatus.draft

    def queue_summary(self, resource: object) -> ApprovalResourceQueueSummary:
        item = self._item(resource)
        context = self.context(item)
        return ApprovalResourceQueueSummary(
            resource_type=self.resource_type,
            resource_id=item.id,
            title=item.title,
            status=item.status.value,
            current_revision=item.content_revision,
            approved_revision=item.approved_revision,
            campaign_id=context.campaign_id,
            campaign_name=context.campaign_name,
            artist_id=context.artist_id,
            artist_name=context.artist_name,
            release_id=context.release_id,
            release_title=context.release_title,
            channels=self.channels(item),
        )

    def approved_revision_is_current(
        self,
        resource: object,
        approval_request: ApprovalRequest,
    ) -> bool:
        item = self._item(resource)
        return (
            item.approved_revision == approval_request.resource_revision
            and item.approved_revision == item.content_revision
        )

    def queue_filter(
        self,
        *,
        organization_id: UUID,
        campaign_id: UUID | None = None,
        artist_id: UUID | None = None,
    ) -> ColumnElement[bool] | None:
        conditions: list[ColumnElement[bool]] = [
            MarketingContentItem.organization_id == organization_id,
            MarketingContentItem.id == ApprovalRequest.resource_id,
        ]
        if campaign_id is not None:
            conditions.append(MarketingContentItem.campaign_id == campaign_id)
        if artist_id is not None:
            conditions.append(MarketingContentItem.artist_id == artist_id)
        if len(conditions) == 2:
            return None
        return select(MarketingContentItem.id).where(*conditions).exists()

    def _item(self, resource: object) -> MarketingContentItem:
        if not isinstance(resource, MarketingContentItem):
            raise TypeError("resource must be a MarketingContentItem")
        return resource


_RESOURCE_ADAPTERS: Mapping[str, ApprovalResourceAdapter] = {
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE: MarketingContentItemApprovalResourceAdapter(),
}


def get_approval_resource_adapter(resource_type: str) -> ApprovalResourceAdapter:
    adapter = _RESOURCE_ADAPTERS.get(resource_type)
    if adapter is None:
        raise UnsupportedApprovalResourceTypeError(
            f"Unsupported approval resource type: {resource_type}"
        )
    return adapter


def list_approval_resource_types() -> Sequence[str]:
    return tuple(_RESOURCE_ADAPTERS)
