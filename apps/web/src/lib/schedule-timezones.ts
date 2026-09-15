import { Temporal } from "@js-temporal/polyfill";

export type ScheduleDisambiguation = "" | "earlier" | "later";

export class ScheduleValidationError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export function validateAuthoringTimezone(timeZone: string) {
  if (!timeZone) {
    throw new ScheduleValidationError("timezone_required", "Select an authoring timezone.");
  }
  if (timeZone !== "UTC" && !timeZone.includes("/")) {
    throw new ScheduleValidationError(
      "invalid_timezone",
      "Use an IANA timezone, not an abbreviation.",
    );
  }
  try {
    Temporal.Instant.fromEpochMilliseconds(0).toZonedDateTimeISO(timeZone);
  } catch {
    throw new ScheduleValidationError("invalid_timezone", "Unknown IANA timezone.");
  }
}

export function scheduleOccurrences(localTime: string, timeZone: string) {
  validateAuthoringTimezone(timeZone);
  let local: Temporal.PlainDateTime;
  try {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::[0-5]\d(?:\.\d{1,6})?)?$/.test(localTime)) {
      throw new Error();
    }
    local = Temporal.PlainDateTime.from(localTime, { overflow: "reject" });
    if (local.year < 1) throw new Error();
  } catch {
    throw new ScheduleValidationError("invalid_local_time", "Enter a valid local date and time.");
  }
  const earlier = local.toZonedDateTime(timeZone, { disambiguation: "earlier" });
  const later = local.toZonedDateTime(timeZone, { disambiguation: "later" });
  if (!earlier.toPlainDateTime().equals(local) || !later.toPlainDateTime().equals(local)) {
    throw new ScheduleValidationError(
      "nonexistent_local_time",
      "This local time does not exist because the clocks move forward. Choose another time.",
    );
  }
  return earlier.epochNanoseconds === later.epochNanoseconds ? [earlier] : [earlier, later];
}

export function resolveSchedule(
  localTime: string,
  timeZone: string,
  choice: ScheduleDisambiguation = "",
) {
  const occurrences = scheduleOccurrences(localTime, timeZone);
  if (occurrences.length > 1 && !choice) {
    throw new ScheduleValidationError(
      "disambiguation_required",
      "This local time occurs twice. Select the earlier or later occurrence.",
    );
  }
  const selected = occurrences[choice === "later" ? occurrences.length - 1 : 0]!;
  return {
    scheduled_at: selected.toInstant().toString(),
    schedule_timezone: timeZone,
    schedule_local_time: selected.toPlainDateTime().toString(),
    schedule_offset_seconds: selected.offsetNanoseconds / 1e9,
    ...(choice ? { schedule_disambiguation: choice } : {}),
  };
}

export function scheduleFromInstant(value: string | null, timeZone: string) {
  validateAuthoringTimezone(timeZone);
  if (!value) return { localTime: "", choice: "" as ScheduleDisambiguation };
  let zoned: Temporal.ZonedDateTime;
  try {
    zoned = Temporal.Instant.from(value).toZonedDateTimeISO(timeZone);
  } catch {
    throw new ScheduleValidationError(
      "timestamp_timezone_required",
      "A valid timestamp with an explicit offset is required.",
    );
  }
  // Retain seconds and subsecond precision; datetime-local supports both.
  const localTime = zoned.toPlainDateTime().toString();
  const occurrences = scheduleOccurrences(localTime, timeZone);
  return {
    localTime,
    choice: (occurrences.length > 1
      ? occurrences[0]!.epochNanoseconds === zoned.epochNanoseconds
        ? "earlier"
        : "later"
      : "") as ScheduleDisambiguation,
  };
}

export function occurrenceLabel(value: Temporal.ZonedDateTime) {
  const abbreviation = new Intl.DateTimeFormat("en", {
    timeZone: value.timeZoneId,
    timeZoneName: "short",
  })
    .formatToParts(new Date(value.epochMilliseconds))
    .find((part) => part.type === "timeZoneName")?.value;
  return `${abbreviation} (UTC${value.offset}) — ${value.toInstant().toString()}`;
}
