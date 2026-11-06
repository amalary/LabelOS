import { type MarketingContentItem } from "../../lib/marketing-content";
import { planningFallbackTimeZone } from "./marketing-presentation";
import { dateKeyInTimeZone } from "../../lib/calendar-dates";

export type MarketingScheduleInstance = {
  eventId?: string;
  publication?: NonNullable<MarketingContentItem["publications"]>[number];
  item: MarketingContentItem;
  scheduledAt: string | null;
  dateKey: string | null;
  hasMultipleChannelTimes: boolean;
};

function isWithinRange(value: string, rangeStart: string, rangeEnd: string): boolean {
  const time = new Date(value).getTime();
  return time >= new Date(rangeStart).getTime() && time <= new Date(rangeEnd).getTime();
}

function uniqueScheduledValues(item: MarketingContentItem): string[] {
  return [
    ...new Set(
      item.channels
        .map((channel) => channel.scheduled_at)
        .filter((scheduledAt): scheduledAt is string => Boolean(scheduledAt)),
    ),
  ].sort();
}

export function toScheduleInstance(
  item: MarketingContentItem,
  rangeStart: string,
  rangeEnd: string,
  timeZone = planningFallbackTimeZone,
): MarketingScheduleInstance {
  // Canonical display date: parent scheduled_at first; otherwise earliest channel date relevant
  // to the visible range, falling back to the earliest channel date overall.
  const channelDates = uniqueScheduledValues(item);
  const relevantChannelDate =
    channelDates.find((scheduledAt) => isWithinRange(scheduledAt, rangeStart, rangeEnd)) ?? null;
  const scheduledAt = item.scheduled_at ?? relevantChannelDate ?? channelDates[0] ?? null;
  return {
    dateKey: scheduledAt ? dateKeyInTimeZone(scheduledAt, timeZone) : null,
    hasMultipleChannelTimes: channelDates.length > 1,
    item,
    scheduledAt,
  };
}

export function toScheduleInstances(
  items: MarketingContentItem[],
  rangeStart: string,
  rangeEnd: string,
  timeZone = planningFallbackTimeZone,
): MarketingScheduleInstance[] {
  return items
    .flatMap((item) => {
      const planned = toScheduleInstance(item, rangeStart, rangeEnd, timeZone);
      const published = (item.publications ?? [])
        .filter((fact) => isWithinRange(fact.published_at, rangeStart, rangeEnd))
        .map((fact): MarketingScheduleInstance => ({
          eventId: `publication:${fact.publication_id}:marketing.content.channel_published`,
          publication: fact,
          item,
          scheduledAt: fact.published_at,
          dateKey: dateKeyInTimeZone(fact.published_at, timeZone),
          hasMultipleChannelTimes: false,
        }));
      return [
        ...(planned.scheduledAt && !isWithinRange(planned.scheduledAt, rangeStart, rangeEnd)
          ? []
          : [planned]),
        ...published,
      ];
    })
    .sort((left, right) => {
      const leftTime = left.scheduledAt ? new Date(left.scheduledAt).getTime() : Infinity;
      const rightTime = right.scheduledAt ? new Date(right.scheduledAt).getTime() : Infinity;
      return leftTime - rightTime || left.item.title.localeCompare(right.item.title);
    });
}
