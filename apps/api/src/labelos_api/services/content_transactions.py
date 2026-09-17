"""Composable authoring operations for future scheduling application services.

Use one AsyncSession transaction for source verification, future job writes,
invalidation and outbox records. Commit/rollback only in the outer application.
Existing service functions remain the compatibility commit-owning entrypoints.
No workload identity or scheduling execution authority is implemented here.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC
from uuid import UUID

from labelos_database.models import (
    ApprovalRequest,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
)
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.authorization import AuthorizationActorInput
from labelos_api.repositories import approvals
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
)
from labelos_api.scheduling.contracts import ApprovalEvidence
from labelos_api.scheduling.timezones import schedule_values
from labelos_api.services import (
    approval_service,
    marketing_content_service,
    scheduling_eligibility,
)
from labelos_api.services.marketing_content_service import (
    MarketingContentChannelCreate,
    MarketingContentChannelUpdate,
    MarketingContentItemCreate,
    MarketingContentItemUpdate,
)


@dataclass(frozen=True)
class LockedSchedulingSource:
    """Source records only; valid while the caller holds this transaction's locks.

    This is not activation authorization or an immutable job snapshot. Future
    scheduling must check its dedicated capability, controls, lateness, active
    jobs and idempotency before writing a job in the same transaction.
    """

    item: MarketingContentItem
    channel: MarketingContentItemChannel
    approval: ApprovalEvidence


class MarketingContentTransaction:
    """Authenticated operations in a caller-owned transaction. Never commits.

    The caller must roll back the entire transaction if any operation fails.
    This is a user/AI authoring boundary, not worker authentication.
    """

    def __init__(
        self,
        session: AsyncSession,
        workspace_id: UUID,
        *,
        actor: AuthorizationActorInput,
    ):
        if actor is None:
            raise ValueError(
                "An explicit authoring actor is required; this is not worker authority"
            )
        self.session = session
        self.workspace_id = workspace_id
        self.actor = actor

    async def verify_scheduling_source(
        self,
        content_item_id: UUID,
        channel_id: UUID,
        *,
        expected_content_revision: int,
        expected_schedule_generation: int,
    ) -> LockedSchedulingSource:
        """Lock/reload source and authority; retain locks for subsequent writes."""
        item = await marketing_content_service._load_content_item_for_workspace(
            self.session, self.workspace_id, content_item_id
        )
        await marketing_content_service._require_capability(
            self.session,
            actor=self.actor,
            workspace_id=self.workspace_id,
            capability=marketing_content_service.Capability.marketing_content_view,
            campaign_id=item.campaign_id,
        )
        channel = next((row for row in item.channels if row.id == channel_id), None)
        if channel is None:
            raise marketing_content_service.MarketingContentNotFoundError(
                "Marketing content channel not found"
            )
        if item.content_revision != expected_content_revision:
            raise approval_service.ApprovalStaleResourceRevisionError(
                "Content revision changed"
            )
        if channel.schedule_generation != expected_schedule_generation:
            raise marketing_content_service.MarketingContentLifecycleError(
                "Schedule generation changed"
            )
        evidence = await approvals.load_current_approval_evidence_for_update(
            self.session,
            self.workspace_id,
            MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
            item.id,
            item.content_revision,
        )
        if not scheduling_eligibility.current_approval_matches(
            item, self.workspace_id, evidence
        ):
            raise marketing_content_service.MarketingContentLifecycleError(
                "Scheduling requires completed approval for the current revision"
            )
        if item.status not in {
            MarketingContentItemStatus.approved,
            MarketingContentItemStatus.scheduled,
        }:
            raise marketing_content_service.MarketingContentLifecycleError(
                "Scheduling requires an approved or scheduled parent"
            )
        if channel.scheduled_at is None or channel.schedule_timezone is None:
            raise marketing_content_service.MarketingContentLifecycleError(
                "Scheduling requires channel time and authoring timezone"
            )
        # Only persisted database readback may repair SQLite's missing tzinfo.
        instant = channel.scheduled_at
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        schedule_values(
            scheduled_at=instant,
            schedule_timezone=channel.schedule_timezone,
            schedule_local_time=channel.schedule_local_time,
            schedule_offset_seconds=channel.schedule_offset_seconds,
            schedule_disambiguation=None,
        )
        assert evidence is not None
        return LockedSchedulingSource(item, channel, evidence)

    async def create_content_item(
        self,
        payload: MarketingContentItemCreate,
    ) -> MarketingContentItem:
        return await marketing_content_service._create_content_item(
            self.session, self.workspace_id, payload, actor=self.actor
        )

    async def update_content_item(
        self,
        content_item_id: UUID,
        payload: MarketingContentItemUpdate,
    ) -> MarketingContentItem:
        return await marketing_content_service._update_content_item(
            self.session, self.workspace_id, content_item_id, payload, actor=self.actor
        )

    async def update_content_item_with_channels(
        self,
        content_item_id: UUID,
        payload: MarketingContentItemUpdate,
        channels: Sequence[MarketingContentChannelCreate],
    ) -> MarketingContentItem:
        return await marketing_content_service._update_content_item_with_channels(
            self.session,
            self.workspace_id,
            content_item_id,
            payload,
            channels,
            actor=self.actor,
        )

    async def replace_channels(
        self,
        content_item_id: UUID,
        channels: Sequence[MarketingContentChannelCreate],
    ) -> MarketingContentItem:
        return await marketing_content_service._replace_channels(
            self.session, self.workspace_id, content_item_id, channels, actor=self.actor
        )

    async def update_channel(
        self,
        content_item_id: UUID,
        channel_id: UUID,
        payload: MarketingContentChannelUpdate,
    ) -> MarketingContentItemChannel:
        return await marketing_content_service._update_channel(
            self.session,
            self.workspace_id,
            content_item_id,
            channel_id,
            payload,
            actor=self.actor,
        )

    async def transition_status(
        self,
        content_item_id: UUID,
        status: MarketingContentItemStatus | str,
        *,
        approved_by_profile_id: UUID | None = None,
        assume_approval_capability: bool = False,
    ) -> MarketingContentItem:
        return await marketing_content_service._transition_status(
            self.session,
            self.workspace_id,
            content_item_id,
            status,
            actor=self.actor,
            approved_by_profile_id=approved_by_profile_id,
            assume_approval_capability=assume_approval_capability,
        )

    async def archive_content_item(
        self,
        content_item_id: UUID,
    ) -> MarketingContentItem:
        return await marketing_content_service._archive_content_item(
            self.session, self.workspace_id, content_item_id, actor=self.actor
        )


class ApprovalTransaction:
    """Authenticated operations in a caller-owned transaction. Never commits.

    The caller must roll back the entire transaction if any operation fails.
    This is a user/AI authoring boundary, not worker authentication.
    """

    def __init__(
        self,
        session: AsyncSession,
        workspace_id: UUID,
        *,
        actor: AuthorizationActorInput,
    ):
        if actor is None:
            raise ValueError(
                "An explicit authoring actor is required; this is not worker authority"
            )
        self.session = session
        self.workspace_id = workspace_id
        self.actor = actor

    async def record_current_approval_invalidated(
        self, approval_request_id: UUID, *, reason: str | None = None
    ) -> ApprovalRequest:
        return await approval_service.record_current_approval_invalidated(
            self.session,
            self.workspace_id,
            approval_request_id,
            actor=self.actor,
            reason=reason,
        )

    async def submit_resource_for_approval(
        self,
        resource_type: str,
        resource_id: UUID,
        *,
        summary: str | None = None,
        metadata_json: dict | None = None,
        expected_resource_revision: int | None = None,
    ) -> ApprovalRequest:
        return await approval_service._submit_resource_for_approval(
            self.session,
            self.workspace_id,
            resource_type,
            resource_id,
            actor=self.actor,
            summary=summary,
            metadata_json=metadata_json,
            expected_resource_revision=expected_resource_revision,
        )

    async def assign_stage_reviewer(
        self,
        approval_request_id: UUID,
        assigned_profile_id: UUID | None,
    ) -> ApprovalRequest:
        return await approval_service._assign_stage_reviewer(
            self.session,
            self.workspace_id,
            approval_request_id,
            assigned_profile_id,
            actor=self.actor,
        )

    async def approve_request(
        self,
        approval_request_id: UUID,
        *,
        comment: str | None = None,
        decision_payload: dict | None = None,
    ) -> ApprovalRequest:
        return await approval_service._approve_request(
            self.session,
            self.workspace_id,
            approval_request_id,
            actor=self.actor,
            comment=comment,
            decision_payload=decision_payload,
        )

    async def request_changes(
        self,
        approval_request_id: UUID,
        *,
        comment: str | None = None,
        decision_payload: dict | None = None,
    ) -> ApprovalRequest:
        return await approval_service._request_changes(
            self.session,
            self.workspace_id,
            approval_request_id,
            actor=self.actor,
            comment=comment,
            decision_payload=decision_payload,
        )

    async def reject_request(
        self,
        approval_request_id: UUID,
        *,
        comment: str | None = None,
        decision_payload: dict | None = None,
    ) -> ApprovalRequest:
        return await approval_service._reject_request(
            self.session,
            self.workspace_id,
            approval_request_id,
            actor=self.actor,
            comment=comment,
            decision_payload=decision_payload,
        )

    async def cancel_request(
        self,
        approval_request_id: UUID,
        *,
        reason: str | None = None,
        decision_payload: dict | None = None,
    ) -> ApprovalRequest:
        return await approval_service._cancel_request(
            self.session,
            self.workspace_id,
            approval_request_id,
            actor=self.actor,
            reason=reason,
            decision_payload=decision_payload,
        )

    async def invalidate_request(
        self,
        approval_request_id: UUID,
        *,
        reason: str | None = None,
        decision_payload: dict | None = None,
    ) -> ApprovalRequest:
        return await approval_service._invalidate_request(
            self.session,
            self.workspace_id,
            approval_request_id,
            actor=self.actor,
            reason=reason,
            decision_payload=decision_payload,
        )

    async def resubmit_resource(
        self,
        resource_type: str,
        resource_id: UUID,
        *,
        previous_approval_request_id: UUID,
        summary: str | None = None,
        expected_resource_revision: int | None = None,
    ) -> ApprovalRequest:
        return await approval_service._resubmit_resource(
            self.session,
            self.workspace_id,
            resource_type,
            resource_id,
            previous_approval_request_id=previous_approval_request_id,
            actor=self.actor,
            summary=summary,
            expected_resource_revision=expected_resource_revision,
        )
