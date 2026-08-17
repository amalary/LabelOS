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

  it("formats unavailable timestamps without throwing", () => {
    expect(formatActivityTimestamp("not-a-date", now)).toBe("Time unavailable");
  });
});
