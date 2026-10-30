"use client";
import { useMemo } from "react";
import { calendarVisibleRange, monthDays } from "../../lib/calendar-dates";
import {
  useWorkspaceCalendarContent,
  type MarketingContentListOptions,
  type MarketingContentItemStatus,
} from "../../lib/marketing-content";
import { type CalendarFilters } from "./marketing-presentation";
import { toScheduleInstances, type MarketingScheduleInstance } from "./marketing-schedule";

export function useMarketingCalendar(
  workspaceId: string | null,
  filters: CalendarFilters,
  monthDate: Date,
  timeZone: string,
) {
  const range = useMemo(() => calendarVisibleRange(monthDate, timeZone), [monthDate, timeZone]);

  const calendarOptions = useMemo<MarketingContentListOptions>(
    () => ({
      artist_id: filters.artistId.trim() || null,
      campaign_id: filters.campaignId || null,
      channel: filters.channel || null,
      end: range.end,
      limit: 500,
      offset: 0,
      release_id: filters.releaseId.trim() || null,
      start: range.start,
      status: (filters.status || null) as MarketingContentItemStatus | null,
    }),
    [
      filters.artistId,
      filters.campaignId,
      filters.channel,
      filters.releaseId,
      filters.status,
      range,
    ],
  );

  const calendarContent = useWorkspaceCalendarContent(workspaceId, calendarOptions);

  const items = calendarContent.data?.marketing_content ?? [];

  const scheduleInstances = useMemo(
    () =>
      toScheduleInstances(items, range.start, range.end, timeZone).filter(
        (instance) =>
          (!filters.status ||
            filters.status !== "published" ||
            Boolean(instance.publication) ||
            instance.item.status === "published") &&
          (!instance.publication ||
            !filters.channel ||
            instance.publication.provider === filters.channel),
      ),
    [items, range.end, range.start, timeZone, filters.status, filters.channel],
  );

  const currentMonthDays = useMemo(() => monthDays(monthDate, timeZone), [monthDate, timeZone]);

  const instancesByDay = useMemo(() => {
    const grouped = new Map<string, MarketingScheduleInstance[]>();
    for (const instance of scheduleInstances) {
      if (!instance.dateKey) {
        continue;
      }
      grouped.set(instance.dateKey, [...(grouped.get(instance.dateKey) ?? []), instance]);
    }
    return grouped;
  }, [scheduleInstances]);
  return { range, calendarContent, items, scheduleInstances, currentMonthDays, instancesByDay };
}
