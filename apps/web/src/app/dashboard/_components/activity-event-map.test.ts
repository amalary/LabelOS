import { describe, expect, it } from "vitest";

import { formatActivityTimestamp, mapActivityEvent } from "./activity-event-map";
import type { ActivityEvent } from "./dashboard.types";

const now = new Date("2026-08-12T18:00:00.000Z");

describe("activity event mapping", () => {
  it("maps supported activity event types without presentation markup", () => {
    const event: ActivityEvent = {
      id: "activity-01",
      type: "artist.created",
      entityType: "artist",
      entityId: "artist_nova",
      payload: { name: "NOVA" },
      createdAt: "2026-08-12T17:56:00.000Z",
    };

    expect(mapActivityEvent(event, now)).toEqual({
      id: "activity-01",
      rawType: "artist.created",
      title: "Artist created",
      description: "NOVA was added",
      timestamp: "4 minutes ago",
      tone: "artist",
    });
  });

  it("falls back gracefully for unknown event types", () => {
    const event: ActivityEvent = {
      id: "activity-unknown",
      type: "sync.catalog_imported",
      actor: { displayName: "Mara" },
      entityType: "catalog",
      createdAt: "2026-08-12T16:00:00.000Z",
    };

    expect(mapActivityEvent(event, now)).toMatchObject({
      title: "Sync Catalog Imported",
      description: "Mara made an update to catalog",
      timestamp: "2 hours ago",
      tone: "default",
      rawType: "sync.catalog_imported",
    });
  });

  it("maps member updated events", () => {
    expect(
      mapActivityEvent(
        {
          id: "activity-member-updated",
          type: "member.updated",
          payload: { displayName: "Sarah Jones" },
          createdAt: "2026-08-12T17:59:00.000Z",
        },
        now,
      ),
    ).toMatchObject({
      title: "Member updated",
      description: "Sarah Jones was updated",
      tone: "team",
      rawType: "member.updated",
    });
  });

  it("maps campaign team activity events", () => {
    expect(
      mapActivityEvent(
        {
          id: "activity-campaign-member",
          type: "campaign.member_added",
          payload: {
            campaignName: "Launch Campaign",
            displayName: "Mira Stone",
            responsibilityLabel: "campaign lead",
          },
          createdAt: "2026-08-12T17:59:00.000Z",
        },
        now,
      ),
    ).toMatchObject({
      title: "Campaign member added",
      description: "Mira Stone joined Launch Campaign",
      tone: "campaign",
      rawType: "campaign.member_added",
    });
  });

  it("maps campaign planning and relationship activity events", () => {
    expect(
      mapActivityEvent(
        {
          id: "activity-campaign-goal",
          type: "campaign.goal_completed",
          payload: {
            campaignName: "Launch Campaign",
            goalTitle: "Reach fans",
            status: "completed",
          },
          createdAt: "2026-08-12T17:59:00.000Z",
        },
        now,
      ),
    ).toMatchObject({
      title: "Campaign goal completed",
      description: "Reach fans was completed",
      tone: "campaign",
    });

    expect(
      mapActivityEvent(
        {
          id: "activity-campaign-release",
          type: "campaign.release_associated",
          payload: {
            campaignName: "Launch Campaign",
            releaseTitle: "Alpha Single",
          },
          createdAt: "2026-08-12T17:59:00.000Z",
        },
        now,
      ),
    ).toMatchObject({
      title: "Campaign release associated",
      description: "Alpha Single was linked to Launch Campaign",
      tone: "campaign",
    });
  });

  it("formats unavailable timestamps without throwing", () => {
    expect(formatActivityTimestamp("not-a-date", now)).toBe("Time unavailable");
  });

  it("maps approval activity events by lifecycle action without comment content", () => {
    const baseEvent = {
      id: "activity-approval",
      type: "approval.updated" as const,
      createdAt: "2026-09-03T12:00:00.000Z",
      actor: { userId: "user_01", displayName: "Reviewer" },
      entityType: "approval_request",
      entityId: "approval_01",
      payload: {
        title: "Launch caption",
        eventAction: "changes_requested",
        status: "changes_requested",
        reason: "Private reviewer feedback",
      },
    };

    const mapped = mapActivityEvent(baseEvent, new Date("2026-09-03T12:01:00.000Z"));

    expect(mapped.title).toBe("Changes requested");
    expect(mapped.description).toBe("Launch caption needs changes before approval");
    expect(mapped.description).not.toContain("Private reviewer feedback");
  });
});
