"use client";

import { useMemo } from "react";

import { useOrganizationRealtimeContext } from "../../../lib/realtime/use-organization-realtime";
import type { RecentActivityData } from "./dashboard.types";
import { RecentActivity } from "./recent-activity";

type RealtimeRecentActivityProps = {
  activity: RecentActivityData;
};

const maxActivityItems = 25;

export function RealtimeRecentActivity({ activity }: RealtimeRecentActivityProps) {
  const realtime = useOrganizationRealtimeContext();
  const liveEvents = realtime?.recentActivityEvents ?? [];
  const mergedActivity = useMemo<RecentActivityData>(() => {
    if (liveEvents.length === 0) {
      return activity;
    }

    const seen = new Set<string>();
    const events = [...liveEvents, ...activity.events].filter((event) => {
      if (seen.has(event.id)) {
        return false;
      }
      seen.add(event.id);
      return true;
    });

    return {
      ...activity,
      events: events.slice(0, maxActivityItems),
    };
  }, [activity, liveEvents]);

  return <RecentActivity activity={mergedActivity} />;
}
