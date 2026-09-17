"""Explicit-zone authoring only. These helpers never activate scheduling work."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import LiteralString
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ScheduleValidationError(ValueError):
    def __init__(self, code: LiteralString, message: str) -> None:
        super().__init__(message)
        self.code: LiteralString = code


def authoring_zone(value: str | None) -> ZoneInfo:
    if not value:
        raise ScheduleValidationError(
            "timezone_required", "Select an authoring timezone."
        )
    # UTC is the sole permitted bare name. Reject ambiguous abbreviations even
    # when the host tzdb happens to include a fixed-offset entry such as EST.
    if value != "UTC" and "/" not in value:
        raise ScheduleValidationError(
            "invalid_timezone", "Use an IANA timezone, not an abbreviation."
        )
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleValidationError(
            "invalid_timezone", "Unknown IANA timezone."
        ) from exc


def utc_instant(value: datetime | str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ScheduleValidationError(
                "invalid_timestamp", "Invalid execution timestamp."
            ) from exc
    if not isinstance(value, datetime):
        raise ScheduleValidationError(
            "invalid_timestamp", "Invalid execution timestamp."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScheduleValidationError(
            "timestamp_timezone_required", "Datetime must include timezone information."
        )
    return value.astimezone(UTC)


def local_datetime(value: str) -> datetime:
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?", value
    ):
        raise ScheduleValidationError(
            "invalid_local_time", "Enter a local date and time without an offset."
        )
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ScheduleValidationError(
            "invalid_local_time", "Invalid local date or time."
        ) from exc


@dataclass(frozen=True)
class AuthoredSchedule:
    scheduled_at: datetime
    schedule_timezone: str
    schedule_local_time: str
    schedule_offset_seconds: int


def instant_to_local(value: datetime | str, timezone: str) -> AuthoredSchedule:
    instant = utc_instant(value)
    local = instant.astimezone(authoring_zone(timezone))
    offset = local.utcoffset()
    assert offset is not None
    return AuthoredSchedule(
        instant,
        timezone,
        local.replace(tzinfo=None).isoformat(),
        int(offset.total_seconds()),
    )


def resolve_local_time(
    local_time: str,
    timezone: str | None,
    disambiguation: str | None = None,
    offset_seconds: int | None = None,
) -> AuthoredSchedule:
    zone = authoring_zone(timezone)
    local = local_datetime(local_time)
    if disambiguation not in (None, "earlier", "later"):
        raise ScheduleValidationError(
            "invalid_disambiguation", "Select earlier or later."
        )
    candidates = sorted(
        {
            local.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            for fold in (0, 1)
            if local.replace(tzinfo=zone, fold=fold)
            .astimezone(UTC)
            .astimezone(zone)
            .replace(tzinfo=None)
            == local
        }
    )
    if not candidates:
        raise ScheduleValidationError(
            "nonexistent_local_time",
            "This local time does not exist because the clocks move forward.",
        )
    if len(candidates) > 1 and disambiguation is None and offset_seconds is None:
        raise ScheduleValidationError(
            "disambiguation_required",
            "This local time occurs twice. Select the earlier or later occurrence.",
        )
    chosen = candidates[-1] if disambiguation == "later" else candidates[0]
    if offset_seconds is not None:
        matching = [
            candidate
            for candidate in candidates
            if instant_to_local(candidate, zone.key).schedule_offset_seconds
            == offset_seconds
        ]
        if not matching or (disambiguation is not None and chosen != matching[0]):
            raise ScheduleValidationError(
                "timezone_instant_mismatch",
                "The selected offset does not match the local time and timezone.",
            )
        chosen = matching[0]
    return instant_to_local(chosen, zone.key)


def schedule_values(
    *,
    scheduled_at: datetime | None,
    schedule_timezone: str | None,
    schedule_local_time: str | None,
    schedule_disambiguation: str | None,
    schedule_offset_seconds: int | None,
) -> dict[str, object]:
    instant = utc_instant(scheduled_at) if scheduled_at is not None else None
    if (
        schedule_timezone is None
        and schedule_local_time is None
        and schedule_disambiguation is None
        and schedule_offset_seconds is None
    ):
        # Compatibility input is planning data, never timezone-confirmed intent.
        return {
            "scheduled_at": instant,
            "schedule_timezone": None,
            "schedule_local_time": None,
            "schedule_offset_seconds": None,
        }
    authoring_zone(schedule_timezone)
    if schedule_local_time is None:
        raise ScheduleValidationError(
            "local_time_required", "Provide the authoring local date and time."
        )
    resolved = resolve_local_time(
        schedule_local_time,
        schedule_timezone,
        schedule_disambiguation,
        schedule_offset_seconds,
    )
    if instant is not None and instant != resolved.scheduled_at:
        raise ScheduleValidationError(
            "timezone_instant_mismatch",
            "The timestamp does not match the selected local time and timezone.",
        )
    return {
        "scheduled_at": resolved.scheduled_at,
        "schedule_timezone": resolved.schedule_timezone,
        "schedule_local_time": resolved.schedule_local_time,
        "schedule_offset_seconds": resolved.schedule_offset_seconds,
    }
