from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from labelos_database.models import (
    Campaign,
    CampaignArtist,
    CampaignGoal,
    CampaignMember,
    CampaignMilestone,
    CampaignRelease,
    CampaignStatus,
    CampaignType,
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
from labelos_api.repositories import (
    campaign_planning,
    campaign_relationships,
    campaigns,
)


class CampaignServiceError(ValueError):
    """Base error for campaign business-rule failures."""


class CampaignNotFoundError(CampaignServiceError):
    pass


class CampaignRelationshipError(CampaignServiceError):
    pass


class CampaignLifecycleError(CampaignServiceError):
    pass


class CampaignPlanningItemNotFoundError(CampaignServiceError):
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
MAX_CAMPAIGN_LIST_LIMIT = 100


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


@dataclass(frozen=True, kw_only=True)
class CampaignGoalCreate:
    title: str
    description: str | None = None
    target_value: str | None = None
    success_criteria: str | None = None
    status: str = "active"


@dataclass(frozen=True, kw_only=True)
class CampaignGoalUpdate:
    title: str | None = None
    description: str | None = None
    target_value: str | None = None
    success_criteria: str | None = None
    status: str | None = None


@dataclass(frozen=True, kw_only=True)
class CampaignMilestoneCreate:
    title: str
    description: str | None = None
    target_date: date | None = None
    status: str = "open"
    created_by_user_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class CampaignMilestoneUpdate:
    title: str | None = None
    description: str | None = None
    target_date: date | None = None
    status: str | None = None
    completed_at: datetime | None = None


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


def _validate_list_pagination(*, limit: int, offset: int) -> None:
    if limit < 1 or limit > MAX_CAMPAIGN_LIST_LIMIT:
        raise CampaignRelationshipError("Campaign list limit must be between 1 and 100")
    if offset < 0:
        raise CampaignRelationshipError(
            "Campaign list offset must be greater than or equal to 0"
        )


def _normalize_optional_label(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _actor_user(actor: AuthorizationActorInput | None) -> User | None:
    user = getattr(actor, "user", None)
    return user if isinstance(user, User) else None


def _campaign_member_payload(
    *,
    campaign: Campaign,
    link: CampaignMember,
) -> dict[str, str | None]:
    membership = link.workspace_membership
    profile = membership.profile
    return {
        "campaignId": str(campaign.id),
        "campaignName": campaign.name,
        "workspaceMembershipId": str(membership.id),
        "profileId": str(membership.profile_id),
        "displayName": profile.display_name,
        "participationStatus": link.participation_status,
        "responsibilityLabel": link.responsibility_label,
        "ownerProfileId": (
            str(campaign.owner_profile_id)
            if campaign.owner_profile_id is not None
            else None
        ),
    }


def _campaign_payload(
    campaign: Campaign,
    *,
    action: str,
    changed_fields: list[str] | None = None,
    previous_status: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "action": action,
        "campaignId": str(campaign.id),
        "campaignName": campaign.name,
        "name": campaign.name,
        "status": (
            campaign.status.value
            if isinstance(campaign.status, CampaignStatus)
            else str(campaign.status)
        ),
        "campaignType": (
            campaign.campaign_type.value
            if isinstance(campaign.campaign_type, CampaignType)
            else str(campaign.campaign_type)
        ),
        "ownerProfileId": (
            str(campaign.owner_profile_id)
            if campaign.owner_profile_id is not None
            else None
        ),
        "primaryArtistId": (
            str(campaign.primary_artist_id)
            if campaign.primary_artist_id is not None
            else None
        ),
        "releaseId": (
            str(campaign.release_id) if campaign.release_id is not None else None
        ),
    }
    if changed_fields is not None:
        payload["changedFields"] = ",".join(changed_fields)
    if previous_status is not None:
        payload["previousStatus"] = previous_status
    return payload


async def _publish_campaign_event(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    event_type: RealtimeEventType,
    actor: AuthorizationActorInput | None,
    campaign: Campaign,
    payload: dict[str, object] | None = None,
) -> None:
    await RealtimePublisher(session).publish(
        organization_id=workspace_id,
        event_type=event_type,
        actor=_actor_user(actor),
        entity_type="campaign",
        entity_id=campaign.id,
        payload=payload or _campaign_payload(campaign, action=event_type.value),
    )


async def _publish_campaign_member_event(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    event_type: RealtimeEventType,
    actor: AuthorizationActorInput | None,
    campaign: Campaign,
    link: CampaignMember,
) -> None:
    await RealtimePublisher(session).publish(
        organization_id=workspace_id,
        event_type=event_type,
        actor=_actor_user(actor),
        entity_type="campaign",
        entity_id=campaign.id,
        payload=_campaign_member_payload(campaign=campaign, link=link),
    )


async def _get_campaign_for_event(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
) -> Campaign:
    campaign = await campaigns.get_campaign(session, workspace_id, campaign_id)
    if campaign is None:
        raise CampaignNotFoundError("Campaign not found")
    return campaign


def _goal_payload(
    *,
    campaign: Campaign,
    goal: CampaignGoal,
    action: str,
    changed_fields: list[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "action": action,
        "campaignId": str(campaign.id),
        "campaignName": campaign.name,
        "goalId": str(goal.id),
        "goalTitle": goal.title,
        "title": goal.title,
        "status": goal.status,
        "targetValue": goal.target_value,
    }
    if changed_fields is not None:
        payload["changedFields"] = ",".join(changed_fields)
    return payload


def _milestone_payload(
    *,
    campaign: Campaign,
    milestone: CampaignMilestone,
    action: str,
    changed_fields: list[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "action": action,
        "campaignId": str(campaign.id),
        "campaignName": campaign.name,
        "milestoneId": str(milestone.id),
        "milestoneTitle": milestone.title,
        "title": milestone.title,
        "status": milestone.status,
        "targetDate": (
            milestone.target_date.isoformat()
            if milestone.target_date is not None
            else None
        ),
        "completedAt": (
            milestone.completed_at.isoformat()
            if milestone.completed_at is not None
            else None
        ),
    }
    if changed_fields is not None:
        payload["changedFields"] = ",".join(changed_fields)
    return payload


def _relationship_payload(
    *,
    campaign: Campaign,
    action: str,
    relationship_kind: str | None = None,
    artist_id: UUID | None = None,
    artist_name: str | None = None,
    release_id: UUID | None = None,
    release_title: str | None = None,
) -> dict[str, object]:
    return {
        "action": action,
        "campaignId": str(campaign.id),
        "campaignName": campaign.name,
        "artistId": str(artist_id) if artist_id is not None else None,
        "artistName": artist_name,
        "releaseId": str(release_id) if release_id is not None else None,
        "releaseTitle": release_title,
        "relationshipKind": relationship_kind,
    }


def _is_primary_relationship(value: str | None) -> bool:
    return value == "primary"


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


def _goal_create_values(payload: CampaignGoalCreate) -> dict[str, object]:
    values: dict[str, object] = {
        "title": payload.title,
        "status": payload.status,
    }
    _set_if_not_none(values, "description", payload.description)
    _set_if_not_none(values, "target_value", payload.target_value)
    _set_if_not_none(values, "success_criteria", payload.success_criteria)
    return values


def _goal_update_values(payload: CampaignGoalUpdate) -> dict[str, object]:
    values: dict[str, object] = {}
    _set_if_not_none(values, "title", payload.title)
    _set_if_not_none(values, "description", payload.description)
    _set_if_not_none(values, "target_value", payload.target_value)
    _set_if_not_none(values, "success_criteria", payload.success_criteria)
    _set_if_not_none(values, "status", payload.status)
    return values


def _milestone_create_values(payload: CampaignMilestoneCreate) -> dict[str, object]:
    values: dict[str, object] = {
        "title": payload.title,
        "status": payload.status,
    }
    _set_if_not_none(values, "description", payload.description)
    _set_if_not_none(values, "target_date", payload.target_date)
    _set_if_not_none(values, "created_by_user_id", payload.created_by_user_id)
    return values


def _milestone_update_values(payload: CampaignMilestoneUpdate) -> dict[str, object]:
    values: dict[str, object] = {}
    _set_if_not_none(values, "title", payload.title)
    _set_if_not_none(values, "description", payload.description)
    _set_if_not_none(values, "target_date", payload.target_date)
    _set_if_not_none(values, "status", payload.status)
    _set_if_not_none(values, "completed_at", payload.completed_at)
    return values


async def list_workspace_campaigns(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    limit: int = 50,
    offset: int = 0,
) -> campaigns.CampaignListPage:
    _validate_list_pagination(limit=limit, offset=offset)
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
    )
    return await campaigns.list_campaigns(
        session,
        workspace_id,
        limit=limit,
        offset=offset,
    )


async def _ensure_campaign_exists(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
) -> None:
    if not await campaign_planning.campaign_exists(session, workspace_id, campaign_id):
        raise CampaignNotFoundError("Campaign not found")


async def list_campaign_goals(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> list[CampaignGoal]:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
        campaign_id=campaign_id,
    )
    goals = await campaign_planning.list_goals(session, workspace_id, campaign_id)
    if goals is None:
        raise CampaignNotFoundError("Campaign not found")
    return goals


async def create_campaign_goal(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    payload: CampaignGoalCreate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> CampaignGoal:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    goal = await campaign_planning.create_goal(
        session,
        workspace_id,
        campaign_id,
        _goal_create_values(payload),
    )
    if goal is None:
        raise CampaignNotFoundError("Campaign not found")
    campaign = await _get_campaign_for_event(session, workspace_id, campaign_id)
    await _publish_campaign_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.campaign_goal_created,
        actor=actor,
        campaign=campaign,
        payload=_goal_payload(campaign=campaign, goal=goal, action="created"),
    )
    await session.commit()
    return goal


async def update_campaign_goal(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    goal_id: UUID,
    payload: CampaignGoalUpdate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> CampaignGoal:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    await _ensure_campaign_exists(session, workspace_id, campaign_id)
    values = _goal_update_values(payload)
    goal = await campaign_planning.update_goal(
        session,
        workspace_id,
        campaign_id,
        goal_id,
        values,
    )
    if goal is None:
        raise CampaignPlanningItemNotFoundError("Campaign goal not found")
    campaign = await _get_campaign_for_event(session, workspace_id, campaign_id)
    event_type = (
        RealtimeEventType.campaign_goal_completed
        if values.get("status") == "completed"
        else RealtimeEventType.campaign_goal_updated
    )
    await _publish_campaign_event(
        session,
        workspace_id=workspace_id,
        event_type=event_type,
        actor=actor,
        campaign=campaign,
        payload=_goal_payload(
            campaign=campaign,
            goal=goal,
            action=(
                "completed"
                if event_type == RealtimeEventType.campaign_goal_completed
                else "updated"
            ),
            changed_fields=sorted(values),
        ),
    )
    await session.commit()
    return goal


async def archive_campaign_goal(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    goal_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> CampaignGoal:
    return await update_campaign_goal(
        session,
        workspace_id,
        campaign_id,
        goal_id,
        CampaignGoalUpdate(status="archived"),
        actor=actor,
    )


async def delete_campaign_goal(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    goal_id: UUID,
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
    await _ensure_campaign_exists(session, workspace_id, campaign_id)
    removed = await campaign_planning.delete_goal(
        session,
        workspace_id,
        campaign_id,
        goal_id,
    )
    await session.commit()
    return removed


async def list_campaign_milestones(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> list[CampaignMilestone]:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
        campaign_id=campaign_id,
    )
    milestones = await campaign_planning.list_milestones(
        session,
        workspace_id,
        campaign_id,
    )
    if milestones is None:
        raise CampaignNotFoundError("Campaign not found")
    return milestones


async def create_campaign_milestone(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    payload: CampaignMilestoneCreate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> CampaignMilestone:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    values = _milestone_create_values(payload)
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
    milestone = await campaign_planning.create_milestone(
        session,
        workspace_id,
        campaign_id,
        values,
    )
    if milestone is None:
        raise CampaignNotFoundError("Campaign not found")
    campaign = await _get_campaign_for_event(session, workspace_id, campaign_id)
    await _publish_campaign_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.campaign_milestone_created,
        actor=actor,
        campaign=campaign,
        payload=_milestone_payload(
            campaign=campaign,
            milestone=milestone,
            action="created",
        ),
    )
    await session.commit()
    return milestone


async def update_campaign_milestone(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    milestone_id: UUID,
    payload: CampaignMilestoneUpdate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> CampaignMilestone:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    await _ensure_campaign_exists(session, workspace_id, campaign_id)
    values = _milestone_update_values(payload)
    milestone = await campaign_planning.update_milestone(
        session,
        workspace_id,
        campaign_id,
        milestone_id,
        values,
    )
    if milestone is None:
        raise CampaignPlanningItemNotFoundError("Campaign milestone not found")
    campaign = await _get_campaign_for_event(session, workspace_id, campaign_id)
    event_type = (
        RealtimeEventType.campaign_milestone_completed
        if values.get("status") == "completed"
        else RealtimeEventType.campaign_milestone_updated
    )
    await _publish_campaign_event(
        session,
        workspace_id=workspace_id,
        event_type=event_type,
        actor=actor,
        campaign=campaign,
        payload=_milestone_payload(
            campaign=campaign,
            milestone=milestone,
            action=(
                "completed"
                if event_type == RealtimeEventType.campaign_milestone_completed
                else "updated"
            ),
            changed_fields=sorted(values),
        ),
    )
    await session.commit()
    return milestone


async def complete_campaign_milestone(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    milestone_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> CampaignMilestone:
    return await update_campaign_milestone(
        session,
        workspace_id,
        campaign_id,
        milestone_id,
        CampaignMilestoneUpdate(
            status="completed",
            completed_at=datetime.now(UTC),
        ),
        actor=actor,
    )


async def archive_campaign_milestone(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    milestone_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> CampaignMilestone:
    return await update_campaign_milestone(
        session,
        workspace_id,
        campaign_id,
        milestone_id,
        CampaignMilestoneUpdate(status="archived"),
        actor=actor,
    )


async def delete_campaign_milestone(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    milestone_id: UUID,
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
    await _ensure_campaign_exists(session, workspace_id, campaign_id)
    removed = await campaign_planning.delete_milestone(
        session,
        workspace_id,
        campaign_id,
        milestone_id,
    )
    await session.commit()
    return removed


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
    await _publish_campaign_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.campaign_created,
        actor=actor,
        campaign=campaign,
        payload=_campaign_payload(campaign, action="created"),
    )
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
    await _publish_campaign_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.campaign_updated,
        actor=actor,
        campaign=campaign,
        payload=_campaign_payload(
            campaign,
            action="updated",
            changed_fields=sorted(values),
        ),
    )
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
    previous_status = (
        campaign.status.value
        if isinstance(campaign.status, CampaignStatus)
        else str(campaign.status)
    )
    campaign.status = _assert_valid_transition(campaign.status, status)
    await _publish_campaign_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.campaign_status_changed,
        actor=actor,
        campaign=campaign,
        payload=_campaign_payload(
            campaign,
            action="status_changed",
            changed_fields=["status"],
            previous_status=previous_status,
        ),
    )
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
    campaign = await get_campaign_by_id(session, workspace_id, campaign_id)
    previous_status = (
        campaign.status.value
        if isinstance(campaign.status, CampaignStatus)
        else str(campaign.status)
    )
    campaign.status = _assert_valid_transition(campaign.status, CampaignStatus.archived)
    await _publish_campaign_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.campaign_status_changed,
        actor=actor,
        campaign=campaign,
        payload=_campaign_payload(
            campaign,
            action="archived",
            changed_fields=["status"],
            previous_status=previous_status,
        ),
    )
    await session.commit()
    return campaign


async def add_campaign_member(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    workspace_membership_id: UUID,
    *,
    participation_status: str = "active",
    responsibility_label: str | None = None,
    actor: AuthorizationActorInput | None = None,
) -> CampaignMember:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
        campaign_id=campaign_id,
    )
    campaign = await get_campaign_by_id(session, workspace_id, campaign_id)
    existing = await campaign_relationships.get_campaign_member(
        session,
        workspace_id,
        campaign_id,
        workspace_membership_id,
    )
    link = await campaign_relationships.add_campaign_member(
        session,
        workspace_id,
        campaign_id,
        workspace_membership_id,
        participation_status=participation_status,
        responsibility_label=_normalize_optional_label(responsibility_label),
    )
    if link is None:
        raise CampaignRelationshipError(
            "Campaign and workspace membership must belong to the same workspace"
        )
    loaded_link = await campaign_relationships.get_campaign_member(
        session,
        workspace_id,
        campaign_id,
        workspace_membership_id,
    )
    if loaded_link is None:
        raise CampaignRelationshipError("Campaign member could not be loaded")
    await _publish_campaign_member_event(
        session,
        workspace_id=workspace_id,
        event_type=(
            RealtimeEventType.campaign_member_updated
            if existing is not None
            else RealtimeEventType.campaign_member_added
        ),
        actor=actor,
        campaign=campaign,
        link=loaded_link,
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
    campaign = await get_campaign_by_id(session, workspace_id, campaign_id)
    link = await campaign_relationships.get_campaign_member(
        session,
        workspace_id,
        campaign_id,
        workspace_membership_id,
    )
    removed = await campaign_relationships.remove_campaign_member(
        session,
        workspace_id,
        campaign_id,
        workspace_membership_id,
    )
    if removed and link is not None:
        await _publish_campaign_member_event(
            session,
            workspace_id=workspace_id,
            event_type=RealtimeEventType.campaign_member_removed,
            actor=actor,
            campaign=campaign,
            link=link,
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
    campaign = await _get_campaign_for_event(session, workspace_id, campaign_id)
    loaded_links = await campaign_relationships.list_campaign_artists(
        session,
        workspace_id,
        campaign_id,
    )
    loaded_link = next(
        (item for item in loaded_links or [] if item.artist_id == artist_id),
        None,
    )
    await _publish_campaign_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.campaign_artist_associated,
        actor=actor,
        campaign=campaign,
        payload=_relationship_payload(
            campaign=campaign,
            action="associated",
            artist_id=artist_id,
            artist_name=loaded_link.artist.name if loaded_link is not None else None,
            relationship_kind=link.relationship_kind,
        ),
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
    campaign = await get_campaign_by_id(session, workspace_id, campaign_id)
    links = await campaign_relationships.list_campaign_artists(
        session,
        workspace_id,
        campaign_id,
    )
    link = next((item for item in links or [] if item.artist_id == artist_id), None)
    removed = await campaign_relationships.remove_campaign_artist(
        session,
        workspace_id,
        campaign_id,
        artist_id,
    )
    if removed and link is not None:
        await _publish_campaign_event(
            session,
            workspace_id=workspace_id,
            event_type=RealtimeEventType.campaign_artist_removed,
            actor=actor,
            campaign=campaign,
            payload=_relationship_payload(
                campaign=campaign,
                action="removed",
                artist_id=artist_id,
                artist_name=link.artist.name,
                relationship_kind=link.relationship_kind,
            ),
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
    campaign = await _get_campaign_for_event(session, workspace_id, campaign_id)
    if campaign.release_id is None or _is_primary_relationship(link.relationship_kind):
        campaign.release_id = release_id
    loaded_links = await campaign_relationships.list_campaign_releases(
        session,
        workspace_id,
        campaign_id,
    )
    loaded_link = next(
        (item for item in loaded_links or [] if item.release_id == release_id),
        None,
    )
    await _publish_campaign_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.campaign_release_associated,
        actor=actor,
        campaign=campaign,
        payload=_relationship_payload(
            campaign=campaign,
            action="associated",
            release_id=release_id,
            release_title=(
                loaded_link.release.title if loaded_link is not None else None
            ),
            relationship_kind=link.relationship_kind,
        ),
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
    campaign = await get_campaign_by_id(session, workspace_id, campaign_id)
    links = await campaign_relationships.list_campaign_releases(
        session,
        workspace_id,
        campaign_id,
    )
    link = next((item for item in links or [] if item.release_id == release_id), None)
    removed = await campaign_relationships.remove_campaign_release(
        session,
        workspace_id,
        campaign_id,
        release_id,
    )
    if removed and campaign.release_id == release_id:
        remaining_links = await campaign_relationships.list_campaign_releases(
            session,
            workspace_id,
            campaign_id,
        )
        next_primary = next(
            (
                item
                for item in remaining_links or []
                if _is_primary_relationship(item.relationship_kind)
            ),
            None,
        )
        next_link = next_primary or next(iter(remaining_links or []), None)
        campaign.release_id = next_link.release_id if next_link is not None else None
    if removed and link is not None:
        await _publish_campaign_event(
            session,
            workspace_id=workspace_id,
            event_type=RealtimeEventType.campaign_release_removed,
            actor=actor,
            campaign=campaign,
            payload=_relationship_payload(
                campaign=campaign,
                action="removed",
                release_id=release_id,
                release_title=link.release.title,
                relationship_kind=link.relationship_kind,
            ),
        )
    await session.commit()
    return removed
