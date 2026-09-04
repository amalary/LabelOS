export const calendarFallbackTimeZone = "UTC";

export type CalendarDay = {
  dateKey: string;
  day: number;
  inMonth: boolean;
  isToday: boolean;
  rangeDate: Date;
};

export type CalendarRange = {
  end: string;
  gridEnd: Date;
  gridStart: Date;
  start: string;
};

export type MonthBoundaries = {
  end: Date;
  start: Date;
};

export function datePartsInTimeZone(value: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
    minute: "2-digit",
    month: "2-digit",
    second: "2-digit",
    timeZone,
    year: "numeric",
  }).formatToParts(value);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((entry) => entry.type === type)?.value ?? 0);
  const hour = part("hour");
  return {
    year: part("year"),
    month: part("month"),
    day: part("day"),
    hour: hour === 24 ? 0 : hour,
    minute: part("minute"),
    second: part("second"),
  };
}

export function zonedDateTimeToUtc(
  year: number,
  monthIndex: number,
  day: number,
  hour: number,
  minute: number,
  second: number,
  timeZone: string,
): Date {
  const utcGuess = new Date(Date.UTC(year, monthIndex, day, hour, minute, second));
  const actualParts = datePartsInTimeZone(utcGuess, timeZone);
  const desiredAsUtc = Date.UTC(year, monthIndex, day, hour, minute, second);
  const actualAsUtc = Date.UTC(
    actualParts.year,
    actualParts.month - 1,
    actualParts.day,
    actualParts.hour,
    actualParts.minute,
    actualParts.second,
  );
  return new Date(utcGuess.getTime() + desiredAsUtc - actualAsUtc);
}

export function monthBoundaries(monthDate: Date): MonthBoundaries {
  const year = monthDate.getUTCFullYear();
  const month = monthDate.getUTCMonth();
  return {
    end: new Date(Date.UTC(year, month + 1, 0)),
    start: new Date(Date.UTC(year, month, 1)),
  };
}

export function dayBoundaries(
  dateKey: string,
  timeZone = calendarFallbackTimeZone,
): { end: string; start: string } {
  const [year = 0, month = 1, day = 1] = dateKey.split("-").map(Number);
  return {
    end: zonedDateTimeToUtc(year, month - 1, day, 23, 59, 59, timeZone).toISOString(),
    start: zonedDateTimeToUtc(year, month - 1, day, 0, 0, 0, timeZone).toISOString(),
  };
}

export function calendarVisibleRange(
  monthDate: Date,
  timeZone = calendarFallbackTimeZone,
): CalendarRange {
  const { end: monthEnd, start: monthStart } = monthBoundaries(monthDate);
  const gridStart = new Date(monthStart);
  gridStart.setUTCDate(monthStart.getUTCDate() - monthStart.getUTCDay());
  const gridEnd = new Date(monthEnd);
  gridEnd.setUTCDate(monthEnd.getUTCDate() + (6 - monthEnd.getUTCDay()));
  return {
    end: zonedDateTimeToUtc(
      gridEnd.getUTCFullYear(),
      gridEnd.getUTCMonth(),
      gridEnd.getUTCDate(),
      23,
      59,
      59,
      timeZone,
    ).toISOString(),
    gridEnd,
    gridStart,
    start: zonedDateTimeToUtc(
      gridStart.getUTCFullYear(),
      gridStart.getUTCMonth(),
      gridStart.getUTCDate(),
      0,
      0,
      0,
      timeZone,
    ).toISOString(),
  };
}

export function calendarListRange(
  monthDate: Date,
  timeZone = calendarFallbackTimeZone,
): { end: string; start: string } {
  const { end, start } = monthBoundaries(monthDate);
  return {
    end: zonedDateTimeToUtc(
      end.getUTCFullYear(),
      end.getUTCMonth(),
      end.getUTCDate(),
      23,
      59,
      59,
      timeZone,
    ).toISOString(),
    start: zonedDateTimeToUtc(
      start.getUTCFullYear(),
      start.getUTCMonth(),
      start.getUTCDate(),
      0,
      0,
      0,
      timeZone,
    ).toISOString(),
  };
}

export function dateKeyFromUtcDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

export function dateKeyInTimeZone(value: Date | string, timeZone: string): string {
  const date = typeof value === "string" ? new Date(value) : value;
  const parts = datePartsInTimeZone(date, timeZone);
  return `${parts.year}-${String(parts.month).padStart(2, "0")}-${String(parts.day).padStart(
    2,
    "0",
  )}`;
}

export function backendDateTimeToCalendarDate(value: Date | string, timeZone: string): Date {
  const dateKey = dateKeyInTimeZone(value, timeZone);
  const [year = 0, month = 1, day = 1] = dateKey.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

export function calendarDateKeyForBackendEvent({
  allDay,
  date,
  startsAt,
  timeZone,
}: {
  allDay?: boolean | null;
  date?: string | null;
  startsAt: string;
  timeZone: string;
}): string {
  return allDay && date ? date : dateKeyInTimeZone(startsAt, timeZone);
}

export function currentCalendarMonthDate(timeZone: string, now = new Date()): Date {
  const nowParts = datePartsInTimeZone(now, timeZone);
  return new Date(Date.UTC(nowParts.year, nowParts.month - 1, 1));
}

export function addCalendarMonths(monthDate: Date, amount: number): Date {
  return new Date(Date.UTC(monthDate.getUTCFullYear(), monthDate.getUTCMonth() + amount, 1));
}

export function monthDays(
  monthDate: Date,
  timeZone: string,
  today = new Date(),
): CalendarDay[] {
  const range = calendarVisibleRange(monthDate, timeZone);
  const days: CalendarDay[] = [];
  const todayKey = dateKeyInTimeZone(today, timeZone);
  const cursor = new Date(range.gridStart);
  while (cursor <= range.gridEnd) {
    const rangeDate = new Date(cursor);
    const dateKey = dateKeyFromUtcDate(rangeDate);
    days.push({
      dateKey,
      day: rangeDate.getUTCDate(),
      inMonth: rangeDate.getUTCMonth() === monthDate.getUTCMonth(),
      isToday: dateKey === todayKey,
      rangeDate,
    });
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}

export function formatCalendarMonthTitle(value: Date): string {
  return new Intl.DateTimeFormat("en", { month: "long", timeZone: "UTC", year: "numeric" }).format(
    value,
  );
}

export function formatCalendarDateTime(value: string | null, timeZone: string): string {
  if (!value) {
    return "Unscheduled";
  }
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    month: "short",
    timeZone,
    timeZoneName: "short",
  }).format(new Date(value));
}

export function formatCalendarListDate(value: string | null, timeZone: string): string {
  if (!value) {
    return "Unscheduled";
  }
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    month: "short",
    timeZone,
    weekday: "short",
    year: "numeric",
  }).format(new Date(value));
}
