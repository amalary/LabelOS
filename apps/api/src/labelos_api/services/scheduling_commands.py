"""Human scheduling commands. Caller commits job, audit and outbox together.

Workspace-scoped operation locks serialize idempotency across targets and verbs.
The append-only transition log is the durable command receipt. Replays return the
original job's current representation, even after subsequent state changes.
"""

from hashlib import sha256
from uuid import UUID, uuid5

from labelos_database.capabilities import Capability
from labelos_database.models import (
    MarketingContentItem,
    SchedulingJob,
    SchedulingJobTransition,
)
from sqlalchemy import func, select
from sqlalchemy.orm import lazyload, selectinload

from labelos_api.realtime import RealtimeEventType, RealtimePublisher
from labelos_api.services import marketing_content_service as content
from labelos_api.services.scheduling_activation import (
    ActivateChannelSchedule,
    SchedulingActivationRejected,
    SchedulingActivationService,
)
from labelos_api.services.scheduling_eligibility import (
    SchedulingExecutionMode,
    evaluate_channel_eligibility,
)


async def authorized_item(session, workspace_id, item_id, actor, *, mutate=False):
    capability = (
        Capability.marketing_content_schedule
        if mutate
        else Capability.marketing_content_view
    )
    await content._require_capability(
        session, actor=actor, workspace_id=workspace_id, capability=capability
    )
    item = await session.scalar(
        select(MarketingContentItem)
        .options(
            lazyload("*"), selectinload(MarketingContentItem.channels).lazyload("*")
        )
        .where(
            MarketingContentItem.organization_id == workspace_id,
            MarketingContentItem.id == item_id,
        )
    )
    if item is None:
        raise content.MarketingContentNotFoundError("Not found")
    await content._require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=capability,
        campaign_id=item.campaign_id,
    )
    return item


class SchedulingCommandService(SchedulingActivationService):
    async def _operation_lock(self, operation_id: UUID):
        if self.session.get_bind().dialect.name != "postgresql":
            raise RuntimeError("Scheduling commands require PostgreSQL")
        key = int.from_bytes(
            sha256(f"scheduling:{self.workspace_id}:{operation_id}".encode()).digest()[
                :8
            ],
            "big",
            signed=True,
        )
        await self.session.execute(select(func.pg_advisory_xact_lock(key)))

    async def _receipt(self, operation_id):
        return list(
            await self.session.scalars(
                select(SchedulingJobTransition).where(
                    SchedulingJobTransition.workspace_id == self.workspace_id,
                    SchedulingJobTransition.operation_id == operation_id,
                )
            )
        )

    async def _authorize(self, item_id):
        return await authorized_item(
            self.session, self.workspace_id, item_id, self.actor, mutate=True
        )

    async def activate_command(self, command: ActivateChannelSchedule):
        await self._authorize(command.content_item_id)
        await self._operation_lock(command.operation_id)
        receipts = await self._receipt(command.operation_id)
        if receipts and any(row.operation != "activate" for row in receipts):
            raise SchedulingActivationRejected("idempotency_conflict")
        # Initial activation cannot silently discard cancellation/edit lineage.
        source = await self.repository.lock_activation_source(
            command.content_item_id, command.channel_id
        )
        if not receipts and source.channel is None:
            raise content.MarketingContentNotFoundError("Not found")
        if not receipts:
            previous = await self.session.scalar(
                select(SchedulingJob)
                .where(
                    SchedulingJob.workspace_id == self.workspace_id,
                    SchedulingJob.marketing_content_item_channel_id
                    == command.channel_id,
                )
                .order_by(SchedulingJob.created_at.desc(), SchedulingJob.id.desc())
                .limit(1)
            )
            if previous is not None:
                active = await self.repository.find_active_job(command.channel_id)
                if active:
                    raise SchedulingActivationRejected("active_job_conflict")
                if previous.status != "handed_off":
                    raise SchedulingActivationRejected("replacement_required")
                if source.item.content_revision <= previous.authorized_content_revision:
                    raise SchedulingActivationRejected("already_handed_off")
        return await self.activate(command)

    async def job_command(
        self,
        job_id: UUID,
        *,
        operation: str,
        operation_id: UUID,
        expected_content_revision: int | None = None,
        expected_schedule_generation: int | None = None,
    ):
        job = await self.repository.get_job(job_id)
        if job is None:
            raise content.MarketingContentNotFoundError("Not found")
        await self._authorize(job.marketing_content_item_id)
        await self._operation_lock(operation_id)
        receipts = await self._receipt(operation_id)
        if receipts:
            if operation == "replace":
                result = await self.repository.get_activation_result(operation_id)
                if (
                    result is not None
                    and result.supersedes_job_id == job_id
                    and result.created_by_user_id == self.user.id
                    and result.authorized_content_revision == expected_content_revision
                    and result.schedule_generation == expected_schedule_generation
                ):
                    return result
            elif len(receipts) == 1:
                receipt = receipts[0]
                if (
                    receipt.job_id == job_id
                    and receipt.operation == operation
                    and receipt.actor_kind == "user"
                    and receipt.actor_key == str(self.user.id)
                ):
                    result = await self.repository.get_job(job_id)
                    assert result is not None
                    return result
            raise SchedulingActivationRejected("idempotency_conflict")
        source = await self.repository.lock_activation_source(
            job.marketing_content_item_id, job.marketing_content_item_channel_id
        )
        await content._require_capability(
            self.session,
            actor=self.actor,
            workspace_id=self.workspace_id,
            capability=Capability.marketing_content_schedule,
            campaign_id=source.item.campaign_id,
        )
        job = await self.repository.get_job(job_id)
        assert job is not None
        if operation == "replace":
            if job.status not in ("blocked", "superseded", "cancelled"):
                raise SchedulingActivationRejected("invalid_state_transition")
            if job.status != "cancelled" and (
                source.item.content_revision <= job.authorized_content_revision
                or source.approval is None
                or source.approval.request_id == job.approval_request_id
            ):
                raise SchedulingActivationRejected("replacement_requires_reapproval")
            if job.status == "blocked":
                await self.repository.apply_user_transition(
                    job.id,
                    operation="supersede",
                    operation_id=operation_id,
                    actor_key=str(self.user.id),
                )
            assert expected_content_revision is not None
            assert expected_schedule_generation is not None
            return await self.activate(
                ActivateChannelSchedule(
                    content_item_id=job.marketing_content_item_id,
                    channel_id=job.marketing_content_item_channel_id,
                    operation_id=operation_id,
                    expected_content_revision=expected_content_revision,
                    expected_schedule_generation=expected_schedule_generation,
                    predecessor_job_id=job.id,
                )
            )
        if operation == "revalidate":
            if job.status != "blocked":
                raise SchedulingActivationRejected("invalid_state_transition")
            if not self.controls.authoring_enabled:
                raise SchedulingActivationRejected("authoring_disabled")
            stale = await self.repository.detect_stale_job(job.id)
            if stale:
                raise SchedulingActivationRejected(stale.value)
            assert source.channel is not None and source.campaign is not None
            connection = await self._destination(job.social_account_connection_id)
            result = evaluate_channel_eligibility(
                workspace_id=self.workspace_id,
                item=source.item,
                channel=source.channel,
                evidence=source.approval,
                connection=connection,
                effective_artist_id=source.item.artist_id
                or source.campaign.primary_artist_id,
                expected_content_revision=job.authorized_content_revision,
                execution_mode=SchedulingExecutionMode.automatic,
                controls=self.controls,
            )
            if not result.eligible:
                raise SchedulingActivationRejected(*result.reason_codes)
        elif operation != "cancel":
            raise ValueError("Unsupported command")
        result = await self.repository.apply_user_transition(
            job.id,
            operation=operation,
            operation_id=operation_id,
            actor_key=str(self.user.id),
        )
        await RealtimePublisher(self.session).publish(
            organization_id=self.workspace_id,
            event_type=RealtimeEventType.marketing_content_updated,
            actor=self.user,
            entity_type="marketing_content_item",
            entity_id=result.marketing_content_item_id,
            operation_id=str(uuid5(self.workspace_id, f"scheduling:{operation_id}")),
            payload={
                "contentItemId": str(result.marketing_content_item_id),
                "channelId": str(result.marketing_content_item_channel_id),
                "schedulingJobId": str(result.id),
                "schedulingStatus": result.status.value,
            },
        )
        return result
