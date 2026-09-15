"""Shared read-only scheduling eligibility, separate from parent planning status.

Evidence and controls are trusted server inputs, never API request fields. Results
are observations, not authorization, activation, a due/lease check, or a promise
of durable handoff. Future execution must reload under the contract's locks.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from labelos_database.models import (
    ApprovalRequestStatus,
    ArtistProfile,
    Campaign,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    SocialAccountConnection,
)
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, load_only

from labelos_api.repositories import approvals
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
)
from labelos_api.scheduling.contracts import ApprovalEvidence, SchedulingFeatureControls
from labelos_api.scheduling.timezones import (
    ScheduleValidationError,
    authoring_zone,
    schedule_values,
    utc_instant,
)
from labelos_api.services.social_account_service import (
    DestinationUnavailableReason,
    ResolvedDestination,
    resolved_destination_for_connection,
)

DISABLED_CONTROLS = SchedulingFeatureControls()


class SchedulingExecutionMode(StrEnum):
    disabled = "disabled"
    automatic = "automatic"
    manual = "manual"


@dataclass(frozen=True, kw_only=True)
class SchedulingEligibility:
    eligible: bool
    content_revision: int
    approval_request_id: UUID | None
    scheduled_for: datetime | None
    schedule_timezone: str | None
    destination_resolution: ResolvedDestination | None
    automatic_handoff_eligible: bool
    manual_handoff_required: bool
    execution_mode: SchedulingExecutionMode
    reason_codes: tuple[str, ...]
    explanations: tuple[str, ...]

    def projection(self) -> dict[str, object]:
        """Explicit safe DTO: never serialize the ORM account or provider errors."""
        destination = self.destination_resolution
        return {
            "eligible": self.eligible,
            "content_revision": self.content_revision,
            "approval_request_id": self.approval_request_id,
            "scheduled_for": self.scheduled_for,
            "schedule_timezone": self.schedule_timezone,
            "destination_resolution": (
                {
                    "id": destination.account.id,
                    "usable": destination.usable,
                    "supports_automatic_publication": (
                        destination.supports_automatic_publication
                    ),
                    "requires_assisted_publication": (
                        destination.requires_assisted_publication
                    ),
                    "unavailable_reasons": destination.unavailable_reasons,
                }
                if destination is not None
                else None
            ),
            "automatic_handoff_eligible": self.automatic_handoff_eligible,
            "manual_handoff_required": self.manual_handoff_required,
            "execution_mode": self.execution_mode,
            "reason_codes": self.reason_codes,
            "explanations": self.explanations,
        }


@dataclass(frozen=True, kw_only=True)
class ContentSchedulingReadiness:
    approved_revision_is_current: bool
    planning_can_schedule: bool
    channels: dict[UUID, SchedulingEligibility]


def current_approval_matches(
    item: MarketingContentItem,
    workspace_id: UUID,
    evidence: ApprovalEvidence | None,
) -> bool:
    return (
        item.organization_id == workspace_id
        and item.content_revision >= 1
        and item.approved_revision == item.content_revision
        and evidence is not None
        and evidence.workspace_id == workspace_id
        and evidence.resource_type == MARKETING_CONTENT_ITEM_RESOURCE_TYPE
        and evidence.content_item_id == item.id
        and evidence.content_revision == item.content_revision
        and evidence.status == ApprovalRequestStatus.approved
        and not evidence.invalidated
        and item.approval_request_id in (None, evidence.request_id)
    )


def has_planning_schedule(item: MarketingContentItem) -> bool:
    return item.scheduled_at is not None or any(
        channel.scheduled_at is not None for channel in item.channels
    )


def planning_can_schedule(
    item: MarketingContentItem, *, approval_current: bool
) -> bool:
    """Compatibility action: moving an approved parent to scheduled is planning."""
    return (
        item.status == MarketingContentItemStatus.approved
        and approval_current
        and has_planning_schedule(item)
    )


async def has_current_approval(
    session: AsyncSession, workspace_id: UUID, item: MarketingContentItem
) -> bool:
    evidence = await approvals.load_current_approval_evidence(
        session,
        workspace_id,
        MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
        [(item.id, item.content_revision)],
    )
    return current_approval_matches(item, workspace_id, evidence.get(item.id))


_MESSAGES = {
    "workspace_mismatch": "Content must belong to this workspace.",
    "channel_mismatch": "Select a channel belonging to this content item.",
    "destination_mismatch": (
        "Select an account compatible with this workspace, channel and artist."
    ),
    "stale_content_revision": "Content changed. Reload its current revision.",
    "stale_approval": "This content revision requires a current completed approval.",
    "ineligible_parent_state": "Content must be approved or scheduled.",
    "missing_schedule_intent": "Set a schedule on this channel.",
    "execution_disabled": "Automatic scheduling execution is disabled.",
    "missing_durable_delivery_receiver": "Scheduling delivery is not configured.",
    "connection_unavailable": "Select an available publishing account.",
    "reconnect_required": "Reconnect the selected account before delivery.",
    "manual_delivery_required": (
        "Manual publishing requires a separate delivery workflow."
    ),
    "capability_unavailable": "The selected account cannot publish this content.",
}

_DESTINATION_REASONS = {
    DestinationUnavailableReason.wrong_workspace: "destination_mismatch",
    DestinationUnavailableReason.provider_mismatch: "destination_mismatch",
    DestinationUnavailableReason.wrong_artist: "destination_mismatch",
    DestinationUnavailableReason.no_connection: "connection_unavailable",
    DestinationUnavailableReason.disconnected: "connection_unavailable",
    DestinationUnavailableReason.connection_error: "connection_unavailable",
    DestinationUnavailableReason.reconnect_required: "reconnect_required",
    DestinationUnavailableReason.missing_capability: "capability_unavailable",
}


def evaluate_channel_eligibility(
    *,
    workspace_id: UUID,
    item: MarketingContentItem,
    channel: MarketingContentItemChannel,
    evidence: ApprovalEvidence | None,
    connection: SocialAccountConnection | None,
    effective_artist_id: UUID | None,
    expected_content_revision: int | None = None,
    execution_mode: SchedulingExecutionMode = SchedulingExecutionMode.disabled,
    controls: SchedulingFeatureControls = DISABLED_CONTROLS,
) -> SchedulingEligibility:
    """Evaluate loaded server records without I/O. Naive authoring input fails closed.

    The batch repository adapter alone normalizes SQLite's persisted UTC columns.
    Artist identity follows content.artist_id or campaign.primary_artist_id and
    the existing connection.artist_profile.artist_id mapping.
    """
    reasons: dict[str, str] = {}

    def block(code: str) -> None:
        reasons[code] = _MESSAGES[code]

    owned = item.organization_id == workspace_id
    channel_owned = channel.marketing_content_item_id == item.id
    if not owned:
        block("workspace_mismatch")
    if not channel_owned:
        block("channel_mismatch")

    destination = None
    if (
        channel.social_account_connection_id is not None
        and connection is not None
        and connection.id == channel.social_account_connection_id
    ):
        # Never return a cross-workspace account, even in an internal projection.
        if connection.organization_id != workspace_id or not owned or not channel_owned:
            block("destination_mismatch")
        else:
            destination = resolved_destination_for_connection(
                connection,
                workspace_id=workspace_id,
                provider=channel.channel,
                artist_id=effective_artist_id,
            )
            if any(
                _DESTINATION_REASONS[reason] == "destination_mismatch"
                for reason in destination.unavailable_reasons
            ):
                block("destination_mismatch")
    elif channel.social_account_connection_id is not None:
        block("destination_mismatch")

    if item.content_revision < 1 or (
        expected_content_revision is not None
        and expected_content_revision != item.content_revision
    ):
        block("stale_content_revision")
    approval_current = current_approval_matches(item, workspace_id, evidence)
    if not approval_current:
        block("stale_approval")
    if item.status not in {
        MarketingContentItemStatus.approved,
        MarketingContentItemStatus.scheduled,
    }:
        block("ineligible_parent_state")
    instant = None
    if channel.scheduled_at is None:
        block("missing_schedule_intent")
    if channel.scheduled_at is not None:
        try:
            instant = utc_instant(channel.scheduled_at)
        except ScheduleValidationError as exc:
            reasons[exc.code] = str(exc)
    try:
        authoring_zone(channel.schedule_timezone)
        if instant is not None:
            schedule_values(
                scheduled_at=instant,
                schedule_timezone=channel.schedule_timezone,
                schedule_local_time=channel.schedule_local_time,
                schedule_disambiguation=None,
                schedule_offset_seconds=channel.schedule_offset_seconds,
            )
    except ScheduleValidationError as exc:
        reasons[exc.code] = str(exc)

    if (
        execution_mode
        not in {
            SchedulingExecutionMode.automatic,
            SchedulingExecutionMode.manual,
        }
        or not controls.execution_enabled
    ):
        block("execution_disabled")
    if not controls.delivery_receiver_configured:
        block("missing_durable_delivery_receiver")
    manual = bool(destination and destination.requires_assisted_publication)
    if destination is None:
        block("connection_unavailable")
    else:
        for reason in destination.unavailable_reasons:
            block(_DESTINATION_REASONS[reason])
        if not destination.usable and not destination.unavailable_reasons:
            block("connection_unavailable")
        if manual:
            block("manual_delivery_required")
        elif not destination.supports_automatic_publication:
            block("capability_unavailable")
    # The initial execution contract has no manual job/task creation mode.
    if execution_mode == SchedulingExecutionMode.manual:
        block("manual_delivery_required")
    eligible = not reasons
    return SchedulingEligibility(
        eligible=eligible,
        content_revision=item.content_revision,
        approval_request_id=(
            evidence.request_id
            if evidence is not None
            and owned
            and evidence.workspace_id == workspace_id
            and evidence.content_item_id == item.id
            else None
        ),
        scheduled_for=instant,
        schedule_timezone=channel.schedule_timezone,
        destination_resolution=destination,
        automatic_handoff_eligible=eligible,
        manual_handoff_required=manual,
        execution_mode=execution_mode,
        reason_codes=tuple(reasons),
        explanations=tuple(reasons.values()),
    )


async def evaluate_content_batch(
    session: AsyncSession,
    workspace_id: UUID,
    items: Sequence[MarketingContentItem],
    *,
    execution_mode: SchedulingExecutionMode = SchedulingExecutionMode.disabled,
    controls: SchedulingFeatureControls = DISABLED_CONTROLS,
) -> dict[UUID, ContentSchedulingReadiness]:
    """Evaluate authorized, loaded parents/channels with three batch SELECTs.

    Connections load only routing/health fields and the existing artist mapping;
    no credentials, credential references, provider metadata, or network access.
    Caller retains transaction ownership. This does not refresh/lock the parents.
    """
    if not items:
        return {}
    evidence = await approvals.load_current_approval_evidence(
        session,
        workspace_id,
        MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
        [(item.id, item.content_revision) for item in items],
    )
    campaign_rows = await session.execute(
        select(Campaign.id, Campaign.primary_artist_id).where(
            Campaign.organization_id == workspace_id,
            Campaign.id.in_({item.campaign_id for item in items}),
        )
    )
    artists = dict(campaign_rows.tuples().all())
    connection_ids = {
        channel.social_account_connection_id
        for item in items
        for channel in item.channels
        if channel.social_account_connection_id is not None
    }
    connections = {}
    if connection_ids:
        rows = await session.scalars(
            select(SocialAccountConnection)
            .options(
                load_only(
                    SocialAccountConnection.id,
                    SocialAccountConnection.organization_id,
                    SocialAccountConnection.artist_profile_id,
                    SocialAccountConnection.provider,
                    SocialAccountConnection.username,
                    SocialAccountConnection.display_name,
                    SocialAccountConnection.connection_method,
                    SocialAccountConnection.status,
                    SocialAccountConnection.capabilities,
                    SocialAccountConnection.last_error_code,
                ),
                joinedload(SocialAccountConnection.artist_profile).load_only(
                    ArtistProfile.artist_id
                ),
            )
            .where(
                SocialAccountConnection.organization_id == workspace_id,
                SocialAccountConnection.id.in_(connection_ids),
            )
            .execution_options(populate_existing=True)
        )
        connections = {connection.id: connection for connection in rows}
    results = {}
    for item in items:
        current = current_approval_matches(item, workspace_id, evidence.get(item.id))
        channels = {}
        for channel in item.channels:
            # Copy the schedule input: never dirty the source ORM record to repair
            # SQLite's timezone loss, and never normalize caller input this way.
            schedule_channel = MarketingContentItemChannel(
                id=channel.id,
                marketing_content_item_id=channel.marketing_content_item_id,
                channel=channel.channel,
                social_account_connection_id=channel.social_account_connection_id,
                scheduled_at=(
                    channel.scheduled_at.replace(tzinfo=UTC)
                    if channel.scheduled_at is not None
                    and channel.scheduled_at.tzinfo is None
                    and inspect(channel).persistent
                    and not inspect(channel).attrs.scheduled_at.history.has_changes()
                    else channel.scheduled_at
                ),
                schedule_timezone=channel.schedule_timezone,
                schedule_local_time=channel.schedule_local_time,
                schedule_offset_seconds=channel.schedule_offset_seconds,
            )
            channels[channel.id] = evaluate_channel_eligibility(
                workspace_id=workspace_id,
                item=item,
                channel=schedule_channel,
                evidence=evidence.get(item.id),
                connection=(
                    connections.get(channel.social_account_connection_id)
                    if channel.social_account_connection_id is not None
                    else None
                ),
                effective_artist_id=item.artist_id or artists.get(item.campaign_id),
                execution_mode=execution_mode,
                controls=controls,
            )
        results[item.id] = ContentSchedulingReadiness(
            approved_revision_is_current=current,
            planning_can_schedule=planning_can_schedule(item, approval_current=current),
            channels=channels,
        )
    return results
