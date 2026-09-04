import { describe, expect, it } from "vitest";

import {
  addCalendarMonths,
  backendDateTimeToCalendarDate,
  calendarDateKeyForBackendEvent,
  calendarListRange,
  calendarVisibleRange,
  currentCalendarMonthDate,
  dateKeyFromUtcDate,
  dateKeyInTimeZone,
  dayBoundaries,
  formatCalendarDateTime,
  formatCalendarListDate,
  formatCalendarMonthTitle,
  monthBoundaries,
  monthDays,
} from "./calendar-dates";

describe("calendar date utilities", () => {
  it("calculates month boundaries in UTC date space", () => {
    const range = monthBoundaries(new Date(Date.UTC(2026, 8, 15)));

    expect(dateKeyFromUtcDate(range.start)).toBe("2026-09-01");
    expect(dateKeyFromUtcDate(range.end)).toBe("2026-09-30");
  });

  it("calculates the visible month range including leading and trailing days", () => {
    const range = calendarVisibleRange(new Date(Date.UTC(2026, 8, 1)), "UTC");

    expect(dateKeyFromUtcDate(range.gridStart)).toBe("2026-08-30");
    expect(dateKeyFromUtcDate(range.gridEnd)).toBe("2026-10-03");
    expect(range.start).toBe("2026-08-30T00:00:00.000Z");
    expect(range.end).toBe("2026-10-03T23:59:59.000Z");
  });

  it("converts visible and list ranges through timezone offsets", () => {
    expect(calendarVisibleRange(new Date(Date.UTC(2026, 8, 1)), "America/Los_Angeles")).toMatchObject(
      {
        start: "2026-08-30T07:00:00.000Z",
        end: "2026-10-04T06:59:59.000Z",
      },
    );
    expect(calendarListRange(new Date(Date.UTC(2026, 8, 1)), "America/Los_Angeles")).toEqual({
      start: "2026-09-01T07:00:00.000Z",
      end: "2026-10-01T06:59:59.000Z",
    });
  });

  it("calculates day boundaries in UTC and timezone-aware local days", () => {
    expect(dayBoundaries("2026-09-10", "UTC")).toEqual({
      start: "2026-09-10T00:00:00.000Z",
      end: "2026-09-10T23:59:59.000Z",
    });
    expect(dayBoundaries("2026-09-10", "America/Los_Angeles")).toEqual({
      start: "2026-09-10T07:00:00.000Z",
      end: "2026-09-11T06:59:59.000Z",
    });
  });

  it("handles DST-sensitive day boundaries", () => {
    expect(dayBoundaries("2026-03-08", "America/Los_Angeles")).toEqual({
      start: "2026-03-08T08:00:00.000Z",
      end: "2026-03-09T06:59:59.000Z",
    });
    expect(dayBoundaries("2026-11-01", "America/Los_Angeles")).toEqual({
      start: "2026-11-01T07:00:00.000Z",
      end: "2026-11-02T07:59:59.000Z",
    });
  });

  it("creates date keys in the requested timezone", () => {
    expect(dateKeyInTimeZone("2026-09-11T06:30:00Z", "America/Los_Angeles")).toBe("2026-09-10");
    expect(dateKeyInTimeZone("2026-09-11T06:30:00Z", "UTC")).toBe("2026-09-11");
  });

  it("converts backend timed datetimes into local calendar dates", () => {
    expect(
      backendDateTimeToCalendarDate("2026-09-11T06:30:00Z", "America/Los_Angeles").toISOString(),
    ).toBe("2026-09-10T00:00:00.000Z");
  });

  it("preserves all-day source dates and timezone-converts timed event dates", () => {
    expect(
      calendarDateKeyForBackendEvent({
        allDay: true,
        date: "2026-09-11",
        startsAt: "2026-09-11T00:00:00Z",
        timeZone: "America/Los_Angeles",
      }),
    ).toBe("2026-09-11");
    expect(
      calendarDateKeyForBackendEvent({
        allDay: false,
        date: null,
        startsAt: "2026-09-11T06:30:00Z",
        timeZone: "America/Los_Angeles",
      }),
    ).toBe("2026-09-10");
  });

  it("builds month grid days with timezone-aware today keys", () => {
    const days = monthDays(
      new Date(Date.UTC(2026, 8, 1)),
      "America/Los_Angeles",
      new Date("2026-09-15T12:00:00Z"),
    );

    expect(days).toHaveLength(35);
    expect(days[0]).toMatchObject({ dateKey: "2026-08-30", day: 30, inMonth: false });
    expect(days.at(-1)).toMatchObject({ dateKey: "2026-10-03", day: 3, inMonth: false });
    expect(days.find((day) => day.isToday)?.dateKey).toBe("2026-09-15");
  });

  it("formats calendar display dates", () => {
    expect(formatCalendarMonthTitle(new Date(Date.UTC(2026, 8, 1)))).toBe("September 2026");
    expect(formatCalendarDateTime(null, "UTC")).toBe("Unscheduled");
    expect(formatCalendarDateTime("2026-09-10T16:00:00Z", "America/Los_Angeles")).toContain(
      "Sep 10",
    );
    expect(formatCalendarListDate("2026-09-10T16:00:00Z", "America/Los_Angeles")).toContain(
      "Sep 10, 2026",
    );
  });

  it("derives the current month and navigates months in UTC date space", () => {
    expect(
      currentCalendarMonthDate(
        "America/Los_Angeles",
        new Date("2026-09-01T01:00:00Z"),
      ).toISOString(),
    ).toBe("2026-08-01T00:00:00.000Z");
    expect(addCalendarMonths(new Date(Date.UTC(2026, 0, 31)), 1).toISOString()).toBe(
      "2026-02-01T00:00:00.000Z",
    );
    expect(addCalendarMonths(new Date(Date.UTC(2026, 0, 1)), -1).toISOString()).toBe(
      "2025-12-01T00:00:00.000Z",
    );
  });
});
