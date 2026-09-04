from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from labelos_database.models import (
    ApprovalRequestStatus,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    Release,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.authorization import (
    AuthorizationActorInput,
    AuthorizationResource,
    Capability,
    ResourceKind,
    authorization_service,
)
from labelos_api.realtime import RealtimeEventType, RealtimePublisher
from labelos_api.repositories import approvals, marketing_content
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
)
from labelos_api.services import approval_service
from labelos_api.services.approval_service import (
    ApprovalDuplicateActiveRequestError,
    ApprovalMissingCapabilityError,
    ApprovalServiceError,
)


class MarketingContentServiceError(ValueError):
    """Base error for marketing content business-rule failures."""


class MarketingContentNotFoundError(MarketingContentServiceError):
    pass


class MarketingContentRelationshipError(MarketingContentServiceError):
    pass


class MarketingContentLifecycleError(MarketingContentServiceError):
    pass


class MarketingContentAuthorizationError(MarketingContentServiceError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


MAX_MARKETING_CONTENT_LIST_LIMIT = 500
APPROVAL_CLEARING_STATUSES = frozenset(
    {
        MarketingContentItemStatus.approved,
        MarketingContentItemStatus.scheduled,
        MarketingContentItemStatus.in_review,
    }
)
MATERIAL_FIELDS = frozenset(
    {
        "title",
        "content_type",
        "copy_text",
        "asset_refs",
        "metadata_json",
        "campaign_id",
        "artist_id",
        "release_id",
        "scheduled_at",
    }
)
CHANNEL_MATERIAL_FIELDS = frozenset(
    {
        "channel",
        "placement",
        "scheduled_at",
        "copy_text_override",
        "asset_refs",
        "metadata_json",
    }
)
ALLOWED_MARKETING_CONTENT_TRANSITIONS: dict[
    MarketingContentItemStatus, frozenset[MarketingContentItemStatus]
] = {
    MarketingContentItemStatus.draft: frozenset(
        {
            MarketingContentItemStatus.in_review,
            MarketingContentItemStatus.cancelled,
            MarketingContentItemStatus.archived,
        }
    ),
    MarketingContentItemStatus.in_review: frozenset(
        {
            MarketingContentItemStatus.draft,
            MarketingContentItemStatus.approved,
            MarketingContentItemStatus.cancelled,
            MarketingContentItemStatus.archived,
        }
    ),
    MarketingContentItemStatus.approved: frozenset(
        {
            MarketingContentItemStatus.draft,
            MarketingContentItemStatus.scheduled,
            MarketingContentItemStatus.cancelled,
            MarketingContentItemStatus.archived,
        }
    ),
    MarketingContentItemStatus.scheduled: frozenset(
        {
            MarketingContentItemStatus.approved,
            MarketingContentItemStatus.published,
            MarketingContentItemStatus.cancelled,
            MarketingContentItemStatus.archived,
        }
    ),
    MarketingContentItemStatus.published: frozenset(
        {MarketingContentItemStatus.archived}
    ),
    MarketingContentItemStatus.cancelled: frozenset(
        {MarketingContentItemStatus.archived}
    ),
    MarketingContentItemStatus.archived: frozenset(),
}


@dataclass(frozen=True, kw_only=True)
class MarketingContentChannelCreate:
    channel: str
    placement: str | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    external_post_id: str | None = None
    external_url: str | None = None
    copy_text_override: str | None = None
    asset_refs: list | None = None
    metadata_json: dict | None = None


@dataclass(frozen=True, kw_only=True)
class MarketingContentChannelUpdate:
    channel: str | None = None
    placement: str | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    external_post_id: str | None = None
    external_url: str | None = None
    copy_text_override: str | None = None
    asset_refs: list | None = None
    metadata_json: dict | None = None


@dataclass(frozen=True, kw_only=True)
class MarketingContentItemCreate:
    campaign_id: UUID
    title: str
    content_type: str
    artist_id: UUID | None = None
    release_id: UUID | None = None
    copy_text: str | None = None
    asset_refs: list | None = None
    metadata_json: dict | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    created_by_user_id: UUID | None = None
    created_by_profile_id: UUID | None = None
    owner_profile_id: UUID | None = None
    channels: Sequence[MarketingContentChannelCreate] = ()


@dataclass(frozen=True, kw_only=True)
class MarketingContentItemUpdate:
    title: str | None = None
    content_type: str | None = None
    artist_id: UUID | None = None
    release_id: UUID | None = None
    copy_text: str | None = None
    asset_refs: list | None = None
    metadata_json: dict | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    owner_profile_id: UUID | None = None
    clear_artist: bool = False
    clear_release: bool = False
    clear_copy_text: bool = False
    clear_scheduled_at: bool = False
    clear_published_at: bool = False
    clear_owner_profile: bool = False
    material_change: bool = False


@dataclass(frozen=True, kw_only=True)
class MarketingContentItemQuery:
    campaign_id: UUID | None = None
    artist_id: UUID | None = None
    release_id: UUID | None = None
    status: MarketingContentItemStatus | str | None = None
    channel: str | None = None
    owner_profile_id: UUID | None = None
    content_type: str | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    published_start: datetime | None = None
    published_end: datetime | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _normalize_text(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise MarketingContentRelationshipError(f"{field_name} is required")
    return value.strip()


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _json_list(value: list | None, field_name: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MarketingContentRelationshipError(f"{field_name} must be a JSON list")
    return value


def _json_object(value: dict | None, field_name: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise MarketingContentRelationshipError(f"{field_name} must be a JSON object")
    return value


def _coerce_status(
    value: MarketingContentItemStatus | str,
) -> MarketingContentItemStatus:
    try:
        return (
            value
            if isinstance(value, MarketingContentItemStatus)
            else MarketingContentItemStatus(value)
        )
    except ValueError as exc:
        raise MarketingContentLifecycleError(
            "Invalid marketing content status"
        ) from exc


def _validate_list_pagination(*, limit: int, offset: int) -> None:
    if limit < 1 or limit > MAX_MARKETING_CONTENT_LIST_LIMIT:
        raise MarketingContentRelationshipError(
            "Marketing content list limit must be between 1 and 500"
        )
    if offset < 0:
        raise MarketingContentRelationshipError(
            "Marketing content list offset must be greater than or equal to 0"
        )


def _normalize_channel_target(
    channel: str | None,
    placement: str | None,
) -> tuple[str, str]:
    normalized_channel = _normalize_text(channel, "channel").lower()
    normalized_placement = _normalize_optional_text(placement)
    return normalized_channel, (normalized_placement or "default").lower()


def _assert_unique_channel_targets(
    values: Sequence[Mapping[str, object]],
) -> None:
    seen: set[tuple[str, str]] = set()
    for value in values:
        target = (str(value["channel"]), str(value["placement"]))
        if target in seen:
            raise MarketingContentRelationshipError(
                "Duplicate channel and placement target"
            )
        seen.add(target)


def _channel_create_values(
    payload: MarketingContentChannelCreate,
) -> dict[str, object]:
    channel, placement = _normalize_channel_target(payload.channel, payload.placement)
    values: dict[str, object] = {
        "channel": channel,
        "placement": placement,
        "asset_refs": _json_list(payload.asset_refs, "asset_refs"),
        "metadata_json": _json_object(payload.metadata_json, "metadata_json"),
    }
    _set_if_not_none(values, "scheduled_at", payload.scheduled_at)
    _set_if_not_none(values, "published_at", payload.published_at)
    _set_if_not_none(
        values,
        "external_post_id",
        _normalize_optional_text(payload.external_post_id),
    )
    _set_if_not_none(
        values, "external_url", _normalize_optional_text(payload.external_url)
    )
    _set_if_not_none(
        values,
        "copy_text_override",
        _normalize_optional_text(payload.copy_text_override),
    )
    return values


def _channel_update_values(
    payload: MarketingContentChannelUpdate,
) -> dict[str, object]:
    values: dict[str, object] = {}
    if payload.channel is not None:
        values["channel"] = _normalize_text(payload.channel, "channel").lower()
    if payload.placement is not None:
        values["placement"] = _normalize_text(payload.placement, "placement").lower()
    _set_if_not_none(values, "scheduled_at", payload.scheduled_at)
    _set_if_not_none(values, "published_at", payload.published_at)
    _set_if_not_none(
        values,
        "external_post_id",
        _normalize_optional_text(payload.external_post_id),
    )
    _set_if_not_none(
        values, "external_url", _normalize_optional_text(payload.external_url)
    )
    _set_if_not_none(
        values,
        "copy_text_override",
        _normalize_optional_text(payload.copy_text_override),
    )
    if payload.asset_refs is not None:
        values["asset_refs"] = _json_list(payload.asset_refs, "asset_refs")
    if payload.metadata_json is not None:
        values["metadata_json"] = _json_object(payload.metadata_json, "metadata_json")
    return values


def _set_if_not_none(values: dict[str, object], key: str, value: object | None) -> None:
    if value is not None:
        values[key] = value


def _actor_user(actor: AuthorizationActorInput | None) -> User | None:
    if isinstance(actor, User):
        return actor
    user = getattr(actor, "user", None)
    return user if isinstance(user, User) else None


def _status_value(status: MarketingContentItemStatus | str) -> str:
    return (
        status.value if isinstance(status, MarketingContentItemStatus) else str(status)
    )


def _content_event_payload(
    item: MarketingContentItem,
    *,
    status: MarketingContentItemStatus | str | None = None,
) -> dict[str, str]:
    payload = {
        "contentItemId": str(item.id),
        "campaignId": str(item.campaign_id),
    }
    if status is not None:
        payload["status"] = _status_value(status)
    return payload


async def _publish_content_event(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    event_type: RealtimeEventType,
    actor: AuthorizationActorInput | None,
    item: MarketingContentItem,
    status: MarketingContentItemStatus | str | None = None,
) -> None:
    await RealtimePublisher(session).publish(
        organization_id=workspace_id,
        event_type=event_type,
        actor=_actor_user(actor),
        entity_type="marketing_content_item",
        entity_id=item.id,
        payload=_content_event_payload(item, status=status),
    )


def _event_type_for_status(
    status: MarketingContentItemStatus,
) -> RealtimeEventType:
    if status == MarketingContentItemStatus.in_review:
        return RealtimeEventType.marketing_content_approval_requested
    if status == MarketingContentItemStatus.approved:
        return RealtimeEventType.marketing_content_approved
    if status == MarketingContentItemStatus.published:
        return RealtimeEventType.marketing_content_published
    return RealtimeEventType.marketing_content_status_changed


def _create_values(payload: MarketingContentItemCreate) -> dict[str, object]:
    values: dict[str, object] = {
        "campaign_id": payload.campaign_id,
        "title": _normalize_text(payload.title, "title"),
        "content_type": _normalize_text(payload.content_type, "content_type").lower(),
        "asset_refs": _json_list(payload.asset_refs, "asset_refs"),
        "metadata_json": _json_object(payload.metadata_json, "metadata_json"),
    }
    _set_if_not_none(values, "artist_id", payload.artist_id)
    _set_if_not_none(values, "release_id", payload.release_id)
    _set_if_not_none(values, "copy_text", _normalize_optional_text(payload.copy_text))
    _set_if_not_none(values, "scheduled_at", payload.scheduled_at)
    _set_if_not_none(values, "published_at", payload.published_at)
    _set_if_not_none(values, "created_by_user_id", payload.created_by_user_id)
    _set_if_not_none(values, "created_by_profile_id", payload.created_by_profile_id)
    _set_if_not_none(values, "owner_profile_id", payload.owner_profile_id)
    return values


def _update_values(payload: MarketingContentItemUpdate) -> dict[str, object]:
    values: dict[str, object] = {}
    _set_if_not_none(values, "title", _normalize_optional_text(payload.title))
    if payload.content_type is not None:
        values["content_type"] = _normalize_text(
            payload.content_type, "content_type"
        ).lower()
    _set_if_not_none(values, "artist_id", payload.artist_id)
    _set_if_not_none(values, "release_id", payload.release_id)
    _set_if_not_none(values, "copy_text", _normalize_optional_text(payload.copy_text))
    if payload.asset_refs is not None:
        values["asset_refs"] = _json_list(payload.asset_refs, "asset_refs")
    if payload.metadata_json is not None:
        values["metadata_json"] = _json_object(payload.metadata_json, "metadata_json")
    _set_if_not_none(values, "scheduled_at", payload.scheduled_at)
    _set_if_not_none(values, "published_at", payload.published_at)
    _set_if_not_none(values, "owner_profile_id", payload.owner_profile_id)
    if payload.clear_artist:
        values["artist_id"] = None
    if payload.clear_release:
        values["release_id"] = None
    if payload.clear_copy_text:
        values["copy_text"] = None
    if payload.clear_scheduled_at:
        values["scheduled_at"] = None
    if payload.clear_published_at:
        values["published_at"] = None
    if payload.clear_owner_profile:
        values["owner_profile_id"] = None
    return values


async def _require_capability(
    session: AsyncSession,
    *,
    actor: AuthorizationActorInput | None,
    workspace_id: UUID,
    capability: Capability,
    campaign_id: UUID | None = None,
) -> None:
    if actor is None:
        return
    resource = AuthorizationResource(
        kind=(
            ResourceKind.campaign if campaign_id is not None else ResourceKind.workspace
        ),
        id=campaign_id or workspace_id,
        workspace_id=workspace_id,
    )
    decision = await authorization_service.decide_capability(
        session,
        actor=actor,
        workspace=workspace_id,
        capability=capability,
        resource=resource,
    )
    if not decision.allowed:
        raise MarketingContentAuthorizationError(decision.reason)


async def _has_approval_capability(
    session: AsyncSession,
    *,
    actor: AuthorizationActorInput | None,
    workspace_id: UUID,
    campaign_id: UUID,
    assume_approval_capability: bool,
) -> bool:
    if actor is None:
        return assume_approval_capability
    try:
        await _require_capability(
            session,
            actor=actor,
            workspace_id=workspace_id,
            capability=Capability.marketing_content_approve,
            campaign_id=campaign_id,
        )
    except MarketingContentAuthorizationError:
        return False
    return True


async def _validate_item_relationships(
    session: AsyncSession,
    workspace_id: UUID,
    values: Mapping[str, object],
) -> None:
    campaign_id = values.get("campaign_id")
    if isinstance(
        campaign_id, UUID
    ) and not await marketing_content.campaign_in_workspace(
        session,
        workspace_id,
        campaign_id,
    ):
        raise MarketingContentNotFoundError("Campaign not found")

    artist_id = values.get("artist_id")
    if isinstance(artist_id, UUID) and not await marketing_content.artist_in_workspace(
        session,
        workspace_id,
        artist_id,
    ):
        raise MarketingContentRelationshipError("artist_id must belong to workspace")

    release_id = values.get("release_id")
    release: Release | None = None
    if isinstance(release_id, UUID):
        release = await marketing_content.release_in_workspace(
            session,
            workspace_id,
            release_id,
        )
        if release is None:
            raise MarketingContentRelationshipError(
                "release_id must belong to workspace"
            )
    if (
        release is not None
        and isinstance(artist_id, UUID)
        and release.artist_id is not None
        and release.artist_id != artist_id
    ):
        raise MarketingContentRelationshipError("release_id must belong to artist_id")

    created_by_user_id = values.get("created_by_user_id")
    if isinstance(
        created_by_user_id,
        UUID,
    ) and not await marketing_content.user_is_active_workspace_member(
        session,
        workspace_id,
        created_by_user_id,
    ):
        raise MarketingContentRelationshipError(
            "created_by_user_id must belong to an active workspace member"
        )

    for field_name in (
        "created_by_profile_id",
        "owner_profile_id",
        "approved_by_profile_id",
    ):
        profile_id = values.get(field_name)
        if isinstance(
            profile_id, UUID
        ) and not await marketing_content.profile_is_active_workspace_member(
            session,
            workspace_id,
            profile_id,
        ):
            raise MarketingContentRelationshipError(
                f"{field_name} must belong to an active workspace member"
            )


def _clear_approval_fields(item: MarketingContentItem) -> None:
    item.approval_requested_at = None
    item.approved_at = None
    item.approved_by_profile_id = None
    item.approved_revision = None
    item.approval_request_id = None


def _assert_transition_allowed(
    current_status: MarketingContentItemStatus | str,
    next_status: MarketingContentItemStatus | str,
) -> MarketingContentItemStatus:
    current = _coerce_status(current_status)
    next_ = _coerce_status(next_status)
    if current == next_:
        return next_
    if next_ not in ALLOWED_MARKETING_CONTENT_TRANSITIONS[current]:
        raise MarketingContentLifecycleError(
            f"Cannot transition marketing content from {current.value} to {next_.value}"
        )
    return next_


def _assert_can_schedule(item: MarketingContentItem) -> None:
    if item.scheduled_at is not None:
        return
    if any(channel.scheduled_at is not None for channel in item.channels):
        return
    raise MarketingContentLifecycleError(
        "scheduled status requires item or channel scheduled_at"
    )


def _value_changed(current: object, proposed: object) -> bool:
    return current != proposed


def _changed_fields(
    item: MarketingContentItem,
    values: Mapping[str, object],
) -> set[str]:
    return {
        field
        for field, value in values.items()
        if _value_changed(getattr(item, field), value)
    }


def _changed_channel_fields(
    channel: MarketingContentItemChannel,
    values: Mapping[str, object],
) -> set[str]:
    return {
        field
        for field, value in values.items()
        if _value_changed(getattr(channel, field), value)
    }


def _channel_signature(channel: MarketingContentItemChannel) -> tuple:
    return (
        channel.channel,
        channel.placement,
        channel.scheduled_at,
        channel.copy_text_override,
        list(channel.asset_refs),
        dict(channel.metadata_json),
    )


def _channel_values_signature(values: Mapping[str, object]) -> tuple:
    return (
        values.get("channel"),
        values.get("placement"),
        values.get("scheduled_at"),
        values.get("copy_text_override"),
        list(values.get("asset_refs", [])),
        dict(values.get("metadata_json", {})),
    )


def _replacement_channels_materially_changed(
    item: MarketingContentItem,
    channel_values: Sequence[Mapping[str, object]],
) -> bool:
    current = sorted(_channel_signature(channel) for channel in item.channels)
    proposed = sorted(_channel_values_signature(values) for values in channel_values)
    return current != proposed


async def _apply_material_change(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    item: MarketingContentItem,
    actor: AuthorizationActorInput | None,
) -> bool:
    approval_was_current = (
        item.approval_request_id is not None
        and item.approved_revision == item.content_revision
    )
    previous_request_id = item.approval_request_id
    if approval_was_current and previous_request_id is not None:
        await approval_service.record_current_approval_invalidated(
            session,
            workspace_id,
            previous_request_id,
            actor=actor,
            reason="Material marketing content edit superseded this approval.",
        )
    item.content_revision += 1
    item.approved_at = None
    item.approved_by_profile_id = None
    if item.status in APPROVAL_CLEARING_STATUSES:
        item.status = MarketingContentItemStatus.draft
        item.approval_requested_at = None
        item.approval_request_id = None
    return approval_was_current


async def _has_completed_approval_for_current_revision(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    item: MarketingContentItem,
) -> bool:
    if item.approved_revision != item.content_revision:
        return False
    request = await approvals.find_conflicting_or_resolved_request(
        session,
        workspace_id,
        MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
        item.id,
        item.content_revision,
    )
    return request is not None and request.status == ApprovalRequestStatus.approved


def _approval_error(exc: ApprovalServiceError) -> MarketingContentServiceError:
    if isinstance(exc, ApprovalMissingCapabilityError):
        return MarketingContentAuthorizationError(exc.reason)
    if isinstance(exc, ApprovalDuplicateActiveRequestError):
        return MarketingContentLifecycleError(str(exc))
    return MarketingContentLifecycleError(str(exc))


async def _load_content_item_for_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    content_item_id: UUID,
) -> MarketingContentItem:
    item = await marketing_content.get_item(session, workspace_id, content_item_id)
    if item is None:
        raise MarketingContentNotFoundError("Marketing content item not found")
    return item


def _capability_for_status_transition(
    next_status: MarketingContentItemStatus,
) -> Capability:
    if next_status == MarketingContentItemStatus.in_review:
        return Capability.marketing_content_submit_for_review
    if next_status == MarketingContentItemStatus.approved:
        return Capability.marketing_content_approve
    if next_status == MarketingContentItemStatus.archived:
        return Capability.marketing_content_archive
    return Capability.marketing_content_edit


async def create_content_item(
    session: AsyncSession,
    workspace_id: UUID,
    payload: MarketingContentItemCreate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> MarketingContentItem:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_content_create,
        campaign_id=payload.campaign_id,
    )
    values = _create_values(payload)
    await _validate_item_relationships(session, workspace_id, values)
    channel_values = [_channel_create_values(channel) for channel in payload.channels]
    _assert_unique_channel_targets(channel_values)
    item = await marketing_content.create_item(session, workspace_id, values)
    if channel_values:
        await marketing_content.create_channels(session, item.id, channel_values)
        session.expire(item, ["channels"])
    await _publish_content_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.marketing_content_created,
        actor=actor,
        item=item,
        status=item.status,
    )
    await session.commit()
    return await get_content_item(session, workspace_id, item.id)


async def get_content_item(
    session: AsyncSession,
    workspace_id: UUID,
    content_item_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> MarketingContentItem:
    item = await marketing_content.get_item(session, workspace_id, content_item_id)
    if item is None:
        raise MarketingContentNotFoundError("Marketing content item not found")
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_content_view,
        campaign_id=item.campaign_id,
    )
    return item


async def get_campaign_content_item(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    content_item_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> MarketingContentItem:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_content_view,
        campaign_id=campaign_id,
    )
    item = await marketing_content.get_item_for_campaign(
        session,
        workspace_id,
        campaign_id,
        content_item_id,
    )
    if item is None:
        raise MarketingContentNotFoundError("Marketing content item not found")
    return item


async def list_content_items(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    query: MarketingContentItemQuery | None = None,
    limit: int = 100,
    offset: int = 0,
) -> marketing_content.MarketingContentItemListPage:
    _validate_list_pagination(limit=limit, offset=offset)
    normalized_query = query or MarketingContentItemQuery()
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_content_view,
        campaign_id=normalized_query.campaign_id,
    )
    if (
        normalized_query.scheduled_start is not None
        and normalized_query.scheduled_end is not None
        and normalized_query.scheduled_end < normalized_query.scheduled_start
    ):
        raise MarketingContentRelationshipError(
            "scheduled_end must be after scheduled_start"
        )
    if (
        normalized_query.published_start is not None
        and normalized_query.published_end is not None
        and normalized_query.published_end < normalized_query.published_start
    ):
        raise MarketingContentRelationshipError(
            "published_end must be after published_start"
        )
    if (
        normalized_query.campaign_id is not None
        and not await marketing_content.campaign_in_workspace(
            session,
            workspace_id,
            normalized_query.campaign_id,
        )
    ):
        raise MarketingContentNotFoundError("Campaign not found")
    if (
        normalized_query.artist_id is not None
        and not await marketing_content.artist_in_workspace(
            session,
            workspace_id,
            normalized_query.artist_id,
        )
    ):
        raise MarketingContentRelationshipError("artist_id must belong to workspace")
    if normalized_query.release_id is not None:
        release = await marketing_content.release_in_workspace(
            session,
            workspace_id,
            normalized_query.release_id,
        )
        if release is None:
            raise MarketingContentRelationshipError(
                "release_id must belong to workspace"
            )
    if (
        normalized_query.owner_profile_id is not None
        and not await marketing_content.profile_is_active_workspace_member(
            session,
            workspace_id,
            normalized_query.owner_profile_id,
        )
    ):
        raise MarketingContentRelationshipError(
            "owner_profile_id must belong to an active workspace member"
        )
    status = (
        _coerce_status(normalized_query.status)
        if normalized_query.status is not None
        else None
    )
    return await marketing_content.list_items(
        session,
        workspace_id,
        campaign_id=normalized_query.campaign_id,
        artist_id=normalized_query.artist_id,
        release_id=normalized_query.release_id,
        status=status,
        channel=(
            _normalize_text(normalized_query.channel, "channel").lower()
            if normalized_query.channel is not None
            else None
        ),
        owner_profile_id=normalized_query.owner_profile_id,
        content_type=(
            _normalize_text(normalized_query.content_type, "content_type").lower()
            if normalized_query.content_type is not None
            else None
        ),
        scheduled_start=normalized_query.scheduled_start,
        scheduled_end=normalized_query.scheduled_end,
        published_start=normalized_query.published_start,
        published_end=normalized_query.published_end,
        limit=limit,
        offset=offset,
    )


async def list_campaign_content_items(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    limit: int = 100,
    offset: int = 0,
) -> marketing_content.MarketingContentItemListPage:
    return await list_content_items(
        session,
        workspace_id,
        actor=actor,
        query=MarketingContentItemQuery(campaign_id=campaign_id),
        limit=limit,
        offset=offset,
    )


async def list_content_items_by_date_range(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    scheduled_start: datetime | None = None,
    scheduled_end: datetime | None = None,
    published_start: datetime | None = None,
    published_end: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> marketing_content.MarketingContentItemListPage:
    return await list_content_items(
        session,
        workspace_id,
        actor=actor,
        query=MarketingContentItemQuery(
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            published_start=published_start,
            published_end=published_end,
        ),
        limit=limit,
        offset=offset,
    )


async def update_content_item(
    session: AsyncSession,
    workspace_id: UUID,
    content_item_id: UUID,
    payload: MarketingContentItemUpdate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> MarketingContentItem:
    item = await _load_content_item_for_workspace(
        session,
        workspace_id,
        content_item_id,
    )
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_content_edit,
        campaign_id=item.campaign_id,
    )
    values = _update_values(payload)
    if not values:
        return item
    relationship_values = dict(values)
    relationship_values.setdefault("campaign_id", item.campaign_id)
    if "artist_id" not in relationship_values and item.artist_id is not None:
        relationship_values["artist_id"] = item.artist_id
    if "release_id" not in relationship_values and item.release_id is not None:
        relationship_values["release_id"] = item.release_id
    await _validate_item_relationships(session, workspace_id, relationship_values)
    changed_fields = _changed_fields(item, values)
    if not changed_fields:
        return item
    material_change = bool(payload.material_change and changed_fields & MATERIAL_FIELDS)
    if material_change:
        await _apply_material_change(
            session,
            workspace_id=workspace_id,
            item=item,
            actor=actor,
        )
    updated = await marketing_content.update_item(
        session,
        workspace_id,
        content_item_id,
        {key: values[key] for key in changed_fields},
    )
    if updated is None:
        raise MarketingContentNotFoundError("Marketing content item not found")
    await _publish_content_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.marketing_content_updated,
        actor=actor,
        item=updated,
        status=updated.status,
    )
    await session.commit()
    return updated


async def replace_channels(
    session: AsyncSession,
    workspace_id: UUID,
    content_item_id: UUID,
    channels: Sequence[MarketingContentChannelCreate],
    *,
    actor: AuthorizationActorInput | None = None,
) -> MarketingContentItem:
    item = await _load_content_item_for_workspace(
        session,
        workspace_id,
        content_item_id,
    )
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_content_edit,
        campaign_id=item.campaign_id,
    )
    channel_values = [_channel_create_values(channel) for channel in channels]
    _assert_unique_channel_targets(channel_values)
    material_change = _replacement_channels_materially_changed(item, channel_values)
    if not material_change:
        return item
    await marketing_content.replace_channels(session, item.id, channel_values)
    session.expire(item, ["channels"])
    await _apply_material_change(
        session,
        workspace_id=workspace_id,
        item=item,
        actor=actor,
    )
    await _publish_content_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.marketing_content_updated,
        actor=actor,
        item=item,
        status=item.status,
    )
    await session.commit()
    return await get_content_item(session, workspace_id, item.id)


async def update_channel(
    session: AsyncSession,
    workspace_id: UUID,
    content_item_id: UUID,
    channel_id: UUID,
    payload: MarketingContentChannelUpdate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> MarketingContentItemChannel:
    item = await _load_content_item_for_workspace(
        session,
        workspace_id,
        content_item_id,
    )
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_content_edit,
        campaign_id=item.campaign_id,
    )
    channel = next((row for row in item.channels if row.id == channel_id), None)
    if channel is None:
        raise MarketingContentNotFoundError("Marketing content channel not found")
    values = _channel_update_values(payload)
    if not values:
        return channel
    changed_fields = _changed_channel_fields(channel, values)
    if not changed_fields:
        return channel
    prospective = []
    for row in item.channels:
        prospective.append(
            {
                "channel": values.get("channel", row.channel),
                "placement": values.get("placement", row.placement),
            }
        )
    _assert_unique_channel_targets(prospective)
    updated = await marketing_content.update_channel(
        session,
        channel_id,
        {key: values[key] for key in changed_fields},
    )
    if updated is None:
        raise MarketingContentNotFoundError("Marketing content channel not found")
    if changed_fields & CHANNEL_MATERIAL_FIELDS:
        await _apply_material_change(
            session,
            workspace_id=workspace_id,
            item=item,
            actor=actor,
        )
    await _publish_content_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.marketing_content_updated,
        actor=actor,
        item=item,
        status=item.status,
    )
    await session.commit()
    return updated


async def transition_status(
    session: AsyncSession,
    workspace_id: UUID,
    content_item_id: UUID,
    status: MarketingContentItemStatus | str,
    *,
    actor: AuthorizationActorInput | None = None,
    approved_by_profile_id: UUID | None = None,
    assume_approval_capability: bool = False,
) -> MarketingContentItem:
    item = await _load_content_item_for_workspace(
        session,
        workspace_id,
        content_item_id,
    )
    next_status = _assert_transition_allowed(item.status, status)
    if next_status == item.status:
        return item
    if next_status == MarketingContentItemStatus.in_review:
        try:
            request = await approval_service.submit_resource_for_approval(
                session,
                workspace_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                content_item_id,
                actor=actor,
            )
        except ApprovalServiceError as exc:
            raise _approval_error(exc) from exc
        return await get_content_item(session, workspace_id, request.resource_id)
    if next_status == MarketingContentItemStatus.approved:
        if item.status == MarketingContentItemStatus.scheduled:
            if not await _has_completed_approval_for_current_revision(
                session,
                workspace_id=workspace_id,
                item=item,
            ):
                raise MarketingContentLifecycleError(
                    "Approved status requires completed approval for the current "
                    "revision"
                )
        else:
            request = await approvals.find_active_request_for_resource_revision(
                session,
                workspace_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                content_item_id,
                item.content_revision,
            )
            if request is None:
                raise MarketingContentLifecycleError(
                    "Approval requires an active generic approval request for the "
                    "current revision"
                )
            try:
                approved = await approval_service.approve_request(
                    session,
                    workspace_id,
                    request.id,
                    actor=actor,
                )
            except ApprovalServiceError as exc:
                raise _approval_error(exc) from exc
            return await get_content_item(session, workspace_id, approved.resource_id)
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=_capability_for_status_transition(next_status),
        campaign_id=item.campaign_id,
    )
    if next_status == MarketingContentItemStatus.scheduled:
        _assert_can_schedule(item)
        if not await _has_completed_approval_for_current_revision(
            session,
            workspace_id=workspace_id,
            item=item,
        ):
            raise MarketingContentLifecycleError(
                "Scheduling requires completed approval for the current revision"
            )
    if next_status == MarketingContentItemStatus.published:
        item.published_at = item.published_at or _now()
    if (
        next_status == MarketingContentItemStatus.draft
        and item.status in APPROVAL_CLEARING_STATUSES
    ):
        _clear_approval_fields(item)
    item.status = next_status
    await _publish_content_event(
        session,
        workspace_id=workspace_id,
        event_type=_event_type_for_status(next_status),
        actor=actor,
        item=item,
        status=next_status,
    )
    await session.commit()
    return item


async def archive_content_item(
    session: AsyncSession,
    workspace_id: UUID,
    content_item_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> MarketingContentItem:
    return await transition_status(
        session,
        workspace_id,
        content_item_id,
        MarketingContentItemStatus.archived,
        actor=actor,
    )
