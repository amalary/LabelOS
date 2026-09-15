"""Storage types for scheduling; these do not authorize or execute work."""

from datetime import UTC, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import JSON, DateTime
from sqlalchemy.types import TypeDecorator


class SchedulingJobStatus(StrEnum):
    pending = "pending"
    claimed = "claimed"
    blocked = "blocked"
    cancelled = "cancelled"
    superseded = "superseded"
    handed_off = "handed_off"


class SchedulingBlockedReason(StrEnum):
    connection_unavailable = "connection_unavailable"
    reconnect_required = "reconnect_required"
    capability_unavailable = "capability_unavailable"
    destination_mismatch = "destination_mismatch"
    manual_delivery_required = "manual_delivery_required"
    stale_content_revision = "stale_content_revision"
    stale_approval = "stale_approval"
    changed_schedule_generation = "changed_schedule_generation"
    missing_durable_delivery_receiver = "missing_durable_delivery_receiver"
    missed_schedule_window = "missed_schedule_window"
    ineligible_parent_state = "ineligible_parent_state"
    missing_schedule_intent = "missing_schedule_intent"
    handoff_contract_violation = "handoff_contract_violation"


class SchedulingUTCDateTime(TypeDecorator[datetime]):
    """Reject naive input and normalize stored instants, including SQLite reads."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Scheduling timestamps must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            if dialect.name != "sqlite":
                raise ValueError("Database returned a naive scheduling timestamp")
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def scheduling_timezone(value: str) -> str:
    if not isinstance(value, str) or (value != "UTC" and "/" not in value):
        raise ValueError("schedule_timezone must be an IANA identifier")
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError("schedule_timezone must be an IANA identifier") from error
    return value


def safe_scheduling_metadata(value: dict | None) -> dict:
    """An allowlist, not free-form provider diagnostics or credential filtering."""
    if not isinstance(value, dict):
        raise ValueError("blocked_metadata must be an object")
    safe = {}
    for key, entry in value.items():
        if key == "reason_codes":
            if not isinstance(entry, list) or len(entry) > len(SchedulingBlockedReason):
                raise ValueError("reason_codes must be a bounded list")
            safe[key] = [SchedulingBlockedReason(reason).value for reason in entry]
        elif key in {
            "observed_content_revision",
            "observed_schedule_generation",
            "lateness_window_seconds",
        }:
            if type(entry) is not int or entry < 0:
                raise ValueError(f"{key} must be a nonnegative integer")
            safe[key] = entry
        else:
            raise ValueError(f"Unsupported scheduling diagnostic field: {key}")
    return safe


class SchedulingMetadata(TypeDecorator[dict]):
    """Validate again at bind time, including Core writes and mutated dictionaries."""

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return safe_scheduling_metadata(value)
