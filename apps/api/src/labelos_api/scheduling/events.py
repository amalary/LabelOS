"""Safe, replayable scheduling outbox records in the transition transaction."""

from uuid import NAMESPACE_URL, UUID, uuid5

from labelos_database.models import RealtimeEvent
from labelos_database.scheduling import SchedulingBlockedReason
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from labelos_api.realtime import RealtimeEventType
from labelos_api.realtime.events import realtime_channel


def job_correlation_id(job) -> UUID:
    # Shared with Delivery; survives retries, lease changes and command replays.
    return uuid5(NAMESPACE_URL, job.idempotency_key)


def transition_events(operation, *, lease_expired=False, unavailable=False):
    names = []
    if lease_expired:
        names.append("lease_expired")
    if unavailable:
        names.append("handoff_unavailable")
    names.append(
        {
            "activate": "activated",
            "claim": "claimed",
            "accept_delivery": "handed_off",
            "block": "blocked",
            "cancel": "cancelled",
            "supersede": "superseded",
            "recover_claim": "requeued",
            "revalidate": "requeued",
        }[operation]
    )
    return tuple(
        RealtimeEventType(f"marketing.scheduling_job.{name}") for name in names
    )


def safe_reason_code(reason: str | None) -> str | None:
    safe_reasons = {r.value for r in SchedulingBlockedReason} | {
        "user_cancelled",
        "database_contention",
        "local_preparation_interrupted",
        "delivery_unavailable",
    }
    return reason if reason in safe_reasons else None


async def publish_transition(session, job, transition, event_types):
    """Only allowlisted scalar fields; never copy content, metadata or errors.

    The existing unique outbox operation key makes retries race-safe. No commit,
    network dispatch or process-local metric is performed before DB commit.
    """
    for event_type in event_types:
        identifier = uuid5(
            job.id, f"scheduling:{transition.transition_version}:{event_type.value}"
        )
        insert = (
            pg_insert
            if session.get_bind().dialect.name == "postgresql"
            else sqlite_insert
        )
        await session.execute(
            insert(RealtimeEvent)
            .values(
                id=identifier,
                organization_id=job.workspace_id,
                channel=realtime_channel(job.workspace_id),
                event_type=event_type.value,
                schema_version=1,
                entity_type="marketing_content_item",
                entity_id=str(job.marketing_content_item_id),
                operation_id=str(identifier),
                actor_user_id=None,
                actor_display_name=None,
                payload={
                    "contentItemId": str(job.marketing_content_item_id),
                    "channelId": str(job.marketing_content_item_channel_id),
                    "schedulingJobId": str(job.id),
                    "schedulingStatus": transition.to_status.value,
                    "transitionVersion": transition.transition_version,
                    "actorKind": transition.actor_kind,
                    "operationId": str(transition.operation_id),
                    "correlationId": str(job_correlation_id(job)),
                    "reasonCode": safe_reason_code(transition.reason_code),
                },
                created_at=transition.created_at,
                updated_at=transition.created_at,
            )
            .on_conflict_do_nothing(index_elements=[RealtimeEvent.operation_id])
        )
