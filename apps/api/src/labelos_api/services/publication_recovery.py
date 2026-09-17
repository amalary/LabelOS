"""Authorized human commands; caller commits resolution history and outbox together."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from labelos_database.models import (
    PublicationAction,
    PublicationLease,
    RealtimeEvent,
    SocialAccountConnection,
)
from labelos_database.publishing import REASONS, PublicResourceURL
from sqlalchemy import select

from labelos_api.publishing.recovery import (
    budget_available,
    latest_action,
    manual_reserved,
    resolution,
)
from labelos_api.publishing.retries import MAX_ELAPSED
from labelos_api.realtime.events import realtime_channel
from labelos_api.repositories.publishing import (
    PublicationConflict,
    PublicationRepository,
)
from labelos_api.repositories.scheduling import SchedulingRepository
from labelos_api.scheduling.payload import canonical_json
from labelos_api.services import marketing_content_service as content
from labelos_api.services.delivery_orchestrator import DeliveryOrchestrator
from labelos_api.services.scheduling_commands import authorized_item


class PublicationHumanRequired(PermissionError):
    pass


class PublicationRecoveryService:
    def __init__(self, session, workspace_id, *, actor, clock=None):
        self.session, self.workspace_id, self.actor = session, workspace_id, actor
        self.repo = PublicationRepository(session, workspace_id)
        self.clock = clock or (lambda: datetime.now(UTC))

    async def get(self, publication_id, *, mutate=False):
        if self.actor is None:
            raise PublicationHumanRequired("authenticated_actor_required")
        row = await self.repo.get(publication_id)
        if row is None:
            raise content.MarketingContentNotFoundError("Not found")
        await authorized_item(
            self.session,
            self.workspace_id,
            row.marketing_content_item_id,
            self.actor,
            mutate=mutate,
        )
        if mutate and (
            content._actor_kind(self.actor) != "user"
            or content._actor_user(self.actor) is None
        ):
            raise PublicationHumanRequired("human_actor_required")
        return row

    async def command(
        self,
        publication_id,
        *,
        operation,
        operation_id: UUID,
        expected_version: int,
        expected_action_version: int,
        external_post_id=None,
        provider_url=None,
    ):
        if operation not in {"begin_manual", "complete_manual", "authorize_retry"}:
            raise PublicationConflict("invalid_recovery_operation")
        if not isinstance(operation_id, UUID) or not operation_id.int:
            raise PublicationConflict("invalid_operation_id")
        if (
            type(expected_version) is not int
            or expected_version < 1
            or type(expected_action_version) is not int
            or expected_action_version < 0
        ):
            raise PublicationConflict("invalid_expected_version")
        if external_post_id is not None and (
            not isinstance(external_post_id, str)
            or not external_post_id.strip()
            or len(external_post_id) > 512
            or any(ord(c) < 32 or ord(c) == 127 for c in external_post_id)
        ):
            raise PublicationConflict("invalid_external_post_id")
        if provider_url is not None:
            try:
                PublicResourceURL().process_bind_param(
                    provider_url, self.session.get_bind().dialect
                )
            except ValueError as exc:
                raise PublicationConflict("invalid_provider_url") from exc
        if operation != "complete_manual" and (external_post_id or provider_url):
            raise PublicationConflict("unexpected_manual_evidence")
        row = await self.get(publication_id, mutate=True)
        actor_user = content._actor_user(self.actor)
        assert actor_user is not None
        # Replay still requires current authorization; take the aggregate lock before
        # checking the immutable command receipt. Source locks come first below.
        if operation != "complete_manual":
            receipt = await self.session.scalar(
                select(PublicationAction).where(
                    PublicationAction.workspace_id == self.workspace_id,
                    PublicationAction.operation_id == operation_id,
                )
            )
            if receipt is None:
                await DeliveryOrchestrator().prepare_execution(
                    SchedulingRepository(
                        self.session, self.workspace_id, lateness_window_seconds=0
                    ),
                    row.id,
                    allow_delivery_blockers=operation == "begin_manual",
                    allow_terminal=operation == "begin_manual",
                )
        row = await self.repo.get(publication_id, lock=True)
        assert row is not None
        receipt = await self.session.scalar(
            select(PublicationAction).where(
                PublicationAction.workspace_id == self.workspace_id,
                PublicationAction.operation_id == operation_id,
            )
        )
        if receipt is not None:
            if (
                receipt.publication_id != row.id
                or receipt.operation != operation
                or receipt.publication_version != expected_version
                or receipt.version != expected_action_version + 1
                or receipt.external_post_id != external_post_id
                or receipt.provider_url != provider_url
                or receipt.actor_id != actor_user.id
            ):
                raise PublicationConflict("idempotency_conflict")
            return row
        if (
            row.transition_version != expected_version
            or len(row.actions) != expected_action_version
        ):
            raise PublicationConflict("publication_version_conflict")
        lease = await self.session.get(PublicationLease, row.id, populate_existing=True)
        if lease and (lease.owner_id is not None or lease.interrupted):
            raise PublicationConflict("execution_requires_reconciliation")
        if row.status not in ("retryable_failure", "permanent_failure"):
            raise PublicationConflict("publication_not_recoverable")
        last = latest_action(row)
        if last and last.operation == "complete_manual":
            raise PublicationConflict("manual_delivery_completed")
        now = self.clock()
        retry_until = None
        if operation == "complete_manual":
            if last is None or last.operation != "begin_manual":
                raise PublicationConflict("manual_reservation_required")
        elif operation == "begin_manual":
            if manual_reserved(row):
                raise PublicationConflict("manual_delivery_reserved")
        else:
            if (
                row.status != "retryable_failure"
                or manual_reserved(row)
                or row.retry_disposition
                not in ("blocked_reconnection", "manual_action")
                or any(
                    a.operation == "authorize_retry"
                    and a.publication_version == row.transition_version
                    for a in row.actions
                )
            ):
                raise PublicationConflict("failure_not_remediable")
            if not budget_available(row, now):
                raise PublicationConflict("retry_budget_exhausted")
            retry_until = row.attempts[0].started_at + MAX_ELAPSED
        reason = resolution(row, now)
        action = PublicationAction(
            workspace_id=self.workspace_id,
            publication_id=row.id,
            version=len(row.actions) + 1,
            publication_version=row.transition_version,
            operation_id=operation_id,
            operation=operation,
            actor_id=actor_user.id,
            reason_code=reason,
            occurred_at=now,
            retry_until=retry_until,
            external_post_id=external_post_id,
            provider_url=provider_url,
        )
        self.session.add(action)
        self.session.add(
            RealtimeEvent(
                organization_id=self.workspace_id,
                channel=realtime_channel(self.workspace_id),
                event_type="marketing.publication.changed",
                entity_type="marketing_content_item",
                entity_id=str(row.marketing_content_item_id),
                operation_id=f"publication-action:{operation_id}",
                payload={
                    "publicationId": str(row.id),
                    "contentItemId": str(row.marketing_content_item_id),
                    "operation": operation,
                    "actionVersion": action.version,
                },
            )
        )
        await self.session.flush()
        return await self.repo.get(row.id)

    async def handoff(self, row):
        """Explicit safe fields only. Never serialize a connection or ORM object."""
        envelope = json.loads(row.canonical_envelope)
        prepared = envelope["content"]
        now = self.clock()
        state = resolution(row, now)
        destination = (
            await self.session.execute(
                select(
                    SocialAccountConnection.external_account_id,
                    SocialAccountConnection.username,
                    SocialAccountConnection.display_name,
                ).where(
                    SocialAccountConnection.organization_id == self.workspace_id,
                    SocialAccountConnection.id == row.social_account_connection_id,
                )
            )
        ).one_or_none()
        identity_matches = bool(
            destination
            and hashlib.sha256(
                canonical_json([row.provider, destination.external_account_id])
            ).hexdigest()
            == row.destination_identity
        )
        reason = {
            "retry_exhausted": "The original automatic retry budget is exhausted.",
            "reconnect_required": (
                "Reconnect the destination with publishing access "
                "before requesting recovery."
            ),
            "reconciliation_required": (
                "The provider may have published. "
                "Reconcile the outcome before any new delivery."
            ),
            "human_intervention_required": (
                "Automation requires human investigation " "and remediation."
            ),
        }.get(state) or {
            "unsupported_operation": (
                "Automated publishing or API access "
                "is unavailable for this destination."
            ),
            "invalid_content_media": (
                "The provider does not support " "this approved content or media."
            ),
            "permanent_rejection": (
                "The provider permanently rejected " "this approved publication."
            ),
        }.get(
            row.failure_category
        )
        completion = latest_action(row) if state == "manually_completed" else None
        # Project only normalized journal evidence. Never include provider responses,
        # execution credentials, the canonical envelope, or arbitrary metadata.
        failures = [t for t in row.transitions if t.failure_reason in REASONS]
        attempts = []
        for attempt in row.attempts:
            observations = [t for t in attempt.observations if t.outcome]
            latest = observations[-1] if observations else None
            attempts.append(
                {
                    "id": attempt.id,
                    "number": attempt.number,
                    "started_at": attempt.started_at,
                    "completed_at": attempt.completed_at,
                    "outcome": attempt.outcome,
                    "failure_reason": (
                        latest.failure_reason
                        if latest and latest.failure_reason in REASONS
                        else None
                    ),
                    "external_post_id": latest.external_post_id if latest else None,
                    "observations": [
                        {
                            "version": t.version,
                            "observed_at": t.observed_at,
                            "outcome": t.outcome,
                            "source": t.source,
                            "failure_reason": (
                                t.failure_reason
                                if t.failure_reason in REASONS
                                else None
                            ),
                        }
                        for t in observations
                    ],
                }
            )
        return {
            "id": row.id,
            "workspace_id": row.workspace_id,
            "content_item_id": row.marketing_content_item_id,
            "channel_id": row.marketing_content_item_channel_id,
            "artist_profile_id": envelope.get("artist_profile_id"),
            "scheduling_job_id": row.scheduling_job_id,
            "schedule_generation": row.schedule_generation,
            "origin": "scheduled",
            "created_at": row.created_at,
            "started_at": row.attempts[0].started_at if row.attempts else None,
            "published_at": row.published_at,
            "last_failed_at": failures[-1].observed_at if failures else None,
            "latest_failure_reason": failures[-1].failure_reason if failures else None,
            "manual_completed_at": completion.occurred_at if completion else None,
            "next_retry_at": row.next_retry_at,
            "attempt_count": len(attempts),
            "attempts": attempts,
            "delivery_status": row.status,
            "resolution": state,
            "completion_source": (
                "human"
                if completion
                else "provider" if row.status == "published" else None
            ),
            "external_post_id": (
                completion.external_post_id if completion else row.external_post_id
            ),
            "provider_url": completion.provider_url if completion else row.provider_url,
            "transition_version": row.transition_version,
            "action_version": len(row.actions),
            "provider": row.provider,
            "destination_id": row.social_account_connection_id,
            "destination_identity_matches": identity_matches,
            "destination_account": (
                dict(destination._mapping)
                if identity_matches and destination is not None
                else None
            ),
            "caption": prepared["caption"],
            "hashtags": prepared["hashtags"],
            "asset_refs": [
                {key: asset[key] for key in ("sha256", "size_bytes", "media_type")}
                for asset in prepared["asset_refs"]
            ],
            "channel": prepared["channel"],
            "placement": prepared["placement"],
            "content_revision": row.authorized_content_revision,
            "scheduled_for": envelope["scheduled_for"],
            "authoring_timezone": envelope["authoring_timezone"],
            "failure_category": row.failure_category,
            "retry_disposition": row.retry_disposition,
            "automation_blocked_reason": (
                state
                if row.status
                in ("retryable_failure", "permanent_failure", "manual_action_required")
                and state
                not in ("retry_scheduled", "retry_authorized", "manually_completed")
                else None
            ),
            "reason": reason,
            "instructions": {
                "manual_publishing": (
                    "Publish the prepared content to the selected destination, "
                    "then confirm manual completion."
                ),
                "manually_completed": (
                    "Manual delivery is recorded. "
                    "Review its history and provider reference."
                ),
                "reconciliation_required": (
                    "Investigate the external outcome. Do not publish again "
                    "until authoritative reconciliation establishes safe absence."
                ),
                "reconnect_required": (
                    "Reconnect the account and request recovery, "
                    "or reserve this publication for manual delivery."
                ),
                "human_intervention_required": (
                    "Investigate and remediate the failure before requesting recovery, "
                    "or reserve this publication for manual delivery."
                ),
                "terminal_failure": "Review the rejection before manual delivery.",
                "retry_exhausted": (
                    "Automatic retries have ended. Reserve for manual delivery."
                ),
                "retry_scheduled": (
                    "An automatic retry is scheduled. Reserve this publication "
                    "first if switching to manual delivery."
                ),
                "retry_authorized": (
                    "Recovery is authorized. The worker will revalidate delivery."
                ),
                "published": "The provider confirmed publication.",
                "cancelled": "This publication was cancelled.",
            }.get(state, "Automatic delivery has not completed."),
            "can_authorize_retry": row.status == "retryable_failure"
            and row.retry_disposition in ("blocked_reconnection", "manual_action")
            and budget_available(row, now)
            and not manual_reserved(row)
            and not any(
                a.operation == "authorize_retry"
                and a.publication_version == row.transition_version
                for a in row.actions
            ),
            "can_begin_manual": row.status in ("retryable_failure", "permanent_failure")
            and not manual_reserved(row),
            "can_complete_manual": state == "manual_publishing",
            "history": [
                {
                    "version": t.version,
                    "operation": t.operation,
                    "from_status": t.from_status,
                    "to_status": t.to_status,
                    "occurred_at": t.occurred_at,
                    "attempt_id": t.attempt_id,
                    "failure_category": t.failure_category,
                    "retry_disposition": t.retry_disposition,
                }
                for t in row.transitions
            ],
            "actions": [
                {
                    "version": a.version,
                    "publication_version": a.publication_version,
                    "operation_id": a.operation_id,
                    "operation": a.operation,
                    "actor_id": a.actor_id,
                    "reason_code": a.reason_code,
                    "occurred_at": a.occurred_at,
                    "external_post_id": a.external_post_id,
                    "provider_url": a.provider_url,
                    "retry_until": a.retry_until,
                }
                for a in row.actions
            ],
        }
