from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from labelos_database.models import (
    Campaign,
    CampaignArtist,
    CampaignMember,
    CampaignRelease,
    CampaignStatus,
    CampaignType,
)
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.authorization import (
    AuthorizationActorInput,
    AuthorizationResource,
    Capability,
    ResourceKind,
    authorization_service,
)
from labelos_api.repositories import campaign_relationships, campaigns


class CampaignServiceError(ValueError):
    """Base error for campaign business-rule failures."""


class CampaignNotFoundError(CampaignServiceError):
    pass


class CampaignRelationshipError(CampaignServiceError):
    pass


class CampaignLifecycleError(CampaignServiceError):
    pass


class CampaignAuthorizationError(CampaignServiceError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


ALLOWED_CAMPAIGN_TRANSITIONS: dict[CampaignStatus, frozenset[CampaignStatus]] = {
    CampaignStatus.draft: frozenset(
        {
            CampaignStatus.planning,
            CampaignStatus.cancelled,
            CampaignStatus.archived,
        }
    ),
    CampaignStatus.planning: frozenset(
        {
            CampaignStatus.draft,
            CampaignStatus.active,
            CampaignStatus.paused,
            CampaignStatus.cancelled,
            CampaignStatus.archived,
        }
    ),
    CampaignStatus.active: frozenset(
        {
            CampaignStatus.paused,
            CampaignStatus.completed,
            CampaignStatus.cancelled,
            CampaignStatus.archived,
        }
    ),
    CampaignStatus.paused: frozenset(
        {
            CampaignStatus.active,
            CampaignStatus.cancelled,
            CampaignStatus.archived,
        }
    ),
    CampaignStatus.completed: frozenset({CampaignStatus.archived}),
    CampaignStatus.cancelled: frozenset({CampaignStatus.archived}),
    CampaignStatus.archived: frozenset(),
}


@dataclass(frozen=True, kw_only=True)
class CampaignCreate:
    name: str
    description: str | None = None
    campaign_type: CampaignType | str = CampaignType.other
    status: CampaignStatus | str = CampaignStatus.draft
    start_date: date | None = None
    target_end_date: date | None = None
    created_by_user_id: UUID | None = None
    created_by_profile_id: UUID | None = None
    owner_profile_id: UUID | None = None
    primary_artist_id: UUID | None = None
    release_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class CampaignUpdate:
    name: str | None = None
    description: str | None = None
    campaign_type: CampaignType | str | None = None
    start_date: date | None = None
    target_end_date: date | None = None
    owner_profile_id: UUID | None = None
    primary_artist_id: UUID | None = None
    release_id: UUID | None = None


def _coerce_campaign_type(value: CampaignType | str) -> CampaignType:
    try:
        return value if isinstance(value, CampaignType) else CampaignType(value)
    except ValueError as exc:
        raise CampaignRelationshipError("Invalid campaign type") from exc


def _coerce_campaign_status(value: CampaignStatus | str) -> CampaignStatus:
    try:
        return value if isinstance(value, CampaignStatus) else CampaignStatus(value)
    except ValueError as exc:
        raise CampaignLifecycleError("Invalid campaign status") from exc


def _assert_valid_transition(
    current_status: CampaignStatus | str,
    next_status: CampaignStatus | str,
) -> CampaignStatus:
    current = _coerce_campaign_status(current_status)
    next_ = _coerce_campaign_status(next_status)
    if current == next_:
        return next_
    if next_ not in ALLOWED_CAMPAIGN_TRANSITIONS[current]:
        raise CampaignLifecycleError(
            f"Cannot transition campaign from {current.value} to {next_.value}"
        )
    return next_


def _set_if_not_none(values: dict[str, object], key: str, value: object | None) -> None:
    if value is not None:
        values[key] = value


async def _validate_profile_relationship(
    session: AsyncSession,
    workspace_id: UUID,
    profile_id: UUID | None,
    field_name: str,
) -> None:
    if profile_id is None:
        return
    if not await campaigns.profile_is_active_workspace_member(
        session,
        workspace_id,
        profile_id,
    ):
        raise CampaignRelationshipError(
            f"{field_name} must belong to an active workspace member"
        )


async def _validate_relationships(
    session: AsyncSession,
    workspace_id: UUID,
    values: Mapping[str, object],
) -> None:
    created_by_user_id = values.get("created_by_user_id")
    if isinstance(
        created_by_user_id,
        UUID,
    ) and not await campaigns.user_is_active_workspace_member(
        session,
        workspace_id,
        created_by_user_id,
    ):
        raise CampaignRelationshipError(
            "created_by_user_id must belong to an active workspace member"
        )

    for field_name in ("created_by_profile_id", "owner_profile_id"):
        profile_id = values.get(field_name)
        if isinstance(profile_id, UUID):
            await _validate_profile_relationship(
                session,
                workspace_id,
                profile_id,
                field_name,
            )

    primary_artist_id = values.get("primary_artist_id")
    if isinstance(primary_artist_id, UUID) and not await campaigns.artist_in_workspace(
        session,
        workspace_id,
        primary_artist_id,
    ):
        raise CampaignRelationshipError("primary_artist_id must belong to workspace")

    release_id = values.get("release_id")
    if isinstance(release_id, UUID) and not await campaigns.release_in_workspace(
        session,
        workspace_id,
        release_id,
    ):
        raise CampaignRelationshipError("release_id must belong to workspace")


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
    resource_kind = (
        ResourceKind.campaign if campaign_id is not None else ResourceKind.workspace
    )
    resource = AuthorizationResource(
        kind=resource_kind,
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
        raise CampaignAuthorizationError(decision.reason)


def _create_values(payload: CampaignCreate) -> dict[str, object]:
    values: dict[str, object] = {
        "name": payload.name,
        "campaign_type": _coerce_campaign_type(payload.campaign_type),
        "status": _coerce_campaign_status(payload.status),
    }
    _set_if_not_none(values, "description", payload.description)
    _set_if_not_none(values, "start_date", payload.start_date)
    _set_if_not_none(values, "target_end_date", payload.target_end_date)
    _set_if_not_none(values, "created_by_user_id", payload.created_by_user_id)
    _set_if_not_none(values, "created_by_profile_id", payload.created_by_profile_id)
    _set_if_not_none(values, "owner_profile_id", payload.owner_profile_id)
    _set_if_not_none(values, "primary_artist_id", payload.primary_artist_id)
    _set_if_not_none(values, "release_id", payload.release_id)
    return values


def _update_values(payload: CampaignUpdate) -> dict[str, object]:
    values: dict[str, object] = {}
    _set_if_not_none(values, "name", payload.name)
    _set_if_not_none(values, "description", payload.description)
    if payload.campaign_type is not None:
        values["campaign_type"] = _coerce_campaign_type(payload.campaign_type)
    _set_if_not_none(values, "start_date", payload.start_date)
    _set_if_not_none(values, "target_end_date", payload.target_end_date)
    _set_if_not_none(values, "owner_profile_id", payload.owner_profile_id)
    _set_if_not_none(values, "primary_artist_id", payload.primary_artist_id)
    _set_if_not_none(values, "release_id", payload.release_id)
    return values


async def list_workspace_campaigns(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> list[Campaign]:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
    )
    return await campaigns.list_campaigns(session, workspace_id)


async def get_campaign_by_id(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> Campaign:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
        campaign_id=campaign_id,
    )
    campaign = await campaigns.get_campaign(session, workspace_id, campaign_id)
    if campaign is None:
        raise CampaignNotFoundError("Campaign not found")
    return campaign


async def create_campaign(
    session: AsyncSession,
    workspace_id: UUID,
    payload: CampaignCreate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> Campaign:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_create,
    )
    values = _create_values(payload)
    await _validate_relationships(session, workspace_id, values)
    campaign = await campaigns.create_campaign(session, workspace_id, values)
    await session.commit()
    return campaign


async def update_campaign(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    payload: CampaignUpdate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> Campaign:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    values = _update_values(payload)
    await _validate_relationships(session, workspace_id, values)
    campaign = await campaigns.update_campaign(
        session,
        workspace_id,
        campaign_id,
        values,
    )
    if campaign is None:
        raise CampaignNotFoundError("Campaign not found")
    await session.commit()
    return campaign


async def change_campaign_status(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    status: CampaignStatus | str,
    *,
    actor: AuthorizationActorInput | None = None,
) -> Campaign:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_approve,
        campaign_id=campaign_id,
    )
    campaign = await get_campaign_by_id(session, workspace_id, campaign_id)
    campaign.status = _assert_valid_transition(campaign.status, status)
    await session.commit()
    return campaign


async def archive_campaign(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> Campaign:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    return await change_campaign_status(
        session,
        workspace_id,
        campaign_id,
        CampaignStatus.archived,
    )


async def add_campaign_member(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    workspace_membership_id: UUID,
    *,
    participation_status: str = "active",
    actor: AuthorizationActorInput | None = None,
) -> CampaignMember:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    link = await campaign_relationships.add_campaign_member(
        session,
        workspace_id,
        campaign_id,
        workspace_membership_id,
        participation_status=participation_status,
    )
    if link is None:
        raise CampaignRelationshipError(
            "Campaign and workspace membership must belong to the same workspace"
        )
    await session.commit()
    return link


async def list_campaign_members(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> list[CampaignMember]:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
        campaign_id=campaign_id,
    )
    links = await campaign_relationships.list_campaign_members(
        session,
        workspace_id,
        campaign_id,
    )
    if links is None:
        raise CampaignNotFoundError("Campaign not found")
    return links


async def remove_campaign_member(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    workspace_membership_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> bool:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    await get_campaign_by_id(session, workspace_id, campaign_id)
    removed = await campaign_relationships.remove_campaign_member(
        session,
        workspace_id,
        campaign_id,
        workspace_membership_id,
    )
    await session.commit()
    return removed


async def list_campaign_artists(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> list[CampaignArtist]:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
        campaign_id=campaign_id,
    )
    links = await campaign_relationships.list_campaign_artists(
        session,
        workspace_id,
        campaign_id,
    )
    if links is None:
        raise CampaignNotFoundError("Campaign not found")
    return links


async def associate_artist(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    artist_id: UUID,
    *,
    relationship_kind: str = "collaborator",
    sort_order: int = 0,
    actor: AuthorizationActorInput | None = None,
) -> CampaignArtist:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    link = await campaign_relationships.add_campaign_artist(
        session,
        workspace_id,
        campaign_id,
        artist_id,
        relationship_kind=relationship_kind,
        sort_order=sort_order,
    )
    if link is None:
        raise CampaignRelationshipError(
            "Campaign and artist must belong to the same workspace"
        )
    await session.commit()
    return link


async def list_campaign_releases(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> list[CampaignRelease]:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
        campaign_id=campaign_id,
    )
    links = await campaign_relationships.list_campaign_releases(
        session,
        workspace_id,
        campaign_id,
    )
    if links is None:
        raise CampaignNotFoundError("Campaign not found")
    return links


async def remove_artist_association(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    artist_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> bool:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    await get_campaign_by_id(session, workspace_id, campaign_id)
    removed = await campaign_relationships.remove_campaign_artist(
        session,
        workspace_id,
        campaign_id,
        artist_id,
    )
    await session.commit()
    return removed


async def associate_release(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    release_id: UUID,
    *,
    relationship_kind: str = "related",
    actor: AuthorizationActorInput | None = None,
) -> CampaignRelease:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    link = await campaign_relationships.add_campaign_release(
        session,
        workspace_id,
        campaign_id,
        release_id,
        relationship_kind=relationship_kind,
    )
    if link is None:
        raise CampaignRelationshipError(
            "Campaign and release must belong to the same workspace"
        )
    await session.commit()
    return link


async def remove_release_association(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    release_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> bool:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    await get_campaign_by_id(session, workspace_id, campaign_id)
    removed = await campaign_relationships.remove_campaign_release(
        session,
        workspace_id,
        campaign_id,
        release_id,
    )
    await session.commit()
    return removed
