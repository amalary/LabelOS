import { describe, expect, it } from "vitest";

import { dateKeyInTimeZone } from "./calendar-dates";
import { resolveSchedule, scheduleFromInstant, scheduleOccurrences } from "./schedule-timezones";

describe("explicit-zone schedule authoring", () => {
  it.each([
    ["UTC", "2027-06-15T09:30:00Z"],
    ["America/Los_Angeles", "2027-06-15T16:30:00Z"],
    ["America/New_York", "2027-06-15T13:30:00Z"],
    ["Asia/Kathmandu", "2027-06-15T03:45:00Z"],
  ])("round trips in %s", (zone, expected) => {
    const result = resolveSchedule("2027-06-15T09:30", zone);
    expect(result.scheduled_at).toBe(expected);
    expect(scheduleFromInstant(expected, zone).localTime).toBe("2027-06-15T09:30:00");
  });

  it.each(["America/Los_Angeles", "America/New_York"])(
    "rejects gaps and requires a fold choice in %s",
    (zone) => {
      for (const choice of ["", "earlier", "later"] as const) {
        expect(() => resolveSchedule("2026-03-08T02:30", zone, choice)).toThrow(/does not exist/);
      }
      expect(() => resolveSchedule("2026-11-01T01:30", zone)).toThrow(/occurs twice/);
      const earlier = resolveSchedule("2026-11-01T01:30", zone, "earlier");
      const later = resolveSchedule("2026-11-01T01:30", zone, "later");
      expect(Date.parse(later.scheduled_at) - Date.parse(earlier.scheduled_at)).toBe(3600000);
      expect(scheduleFromInstant(earlier.scheduled_at, zone).choice).toBe("earlier");
      expect(scheduleFromInstant(later.scheduled_at, zone).choice).toBe("later");
    },
  );

  it.each(["PST", "EST", "America/Invalid", "+05:30", ""])(
    "rejects invalid authoring zone %s",
    (zone) => {
      expect(() => resolveSchedule("2027-06-15T09:30", zone)).toThrow();
    },
  );

  it("rejects naive instants, impossible dates and local times carrying offsets", () => {
    expect(() => scheduleFromInstant("2027-06-15T09:30", "UTC")).toThrow();
    expect(() => resolveSchedule("2027-02-30T09:30", "UTC")).toThrow();
    expect(() => resolveSchedule("2027-06-15T09:30Z", "UTC")).toThrow();
    expect(() => resolveSchedule("2027-06-15T09:30:60", "UTC")).toThrow();
    expect(() => resolveSchedule("0000-01-01T09:30", "UTC")).toThrow();
  });

  it("keeps calendar display independent and preserves subsecond precision", () => {
    const value = resolveSchedule("2027-06-15T23:30:15.123456", "America/Los_Angeles");
    expect(value.scheduled_at).toBe("2027-06-16T06:30:15.123456Z");
    expect(dateKeyInTimeZone(value.scheduled_at, "America/New_York")).toBe("2027-06-16");
    expect(scheduleFromInstant(value.scheduled_at, "America/Los_Angeles").localTime).toBe(
      "2027-06-15T23:30:15.123456",
    );
  });

  it("handles a half-hour DST transition", () => {
    const values = scheduleOccurrences("2026-04-05T01:45", "Australia/Lord_Howe");
    expect(values).toHaveLength(2);
    expect(values[1]!.epochMilliseconds - values[0]!.epochMilliseconds).toBe(1800000);
  });
});
