import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CampaignCalendarApiError,
  campaignCalendarQuery,
  campaignCalendarQueryKeys,
  listCampaignCalendarEvents,
  stableCampaignCalendarQueryKey,
} from "./campaign-calendar";

const calendarEvent = {
  id: "marketing_content:content_01:scheduled",
  event_type: "marketing.content.scheduled",
  source_type: "marketing_content_item",
  source_id: "content_01",
  source_parent_id: "campaign_01",
  title: "Announcement post",
  description: null,
  starts_at: "2026-09-10T09:00:00-07:00",
  ends_at: null,
  date: null,
  all_day: false,
  timezone: "America/Los_Angeles",
  status: "scheduled",
  campaign: {
    id: "campaign_01",
    name: "Launch Campaign",
    status: "active",
    campaign_type: "release",
  },
  artist: {
    id: "artist_01",
    name: "Mira Stone",
  },
  release: {
    id: "release_01",
    title: "Northline",
    artist_id: "artist_01",
  },
  channel: null,
  approval: {
    request_id: "approval_01",
    state: "approved",
    label: "Approved",
    approved_revision_is_current: true,
    can_schedule: true,
    available_actions: [],
  },
  url: null,
  sort_key: "2026-09-10T16:00:00+00:00|marketing.content.scheduled|content_01",
} as const;

describe("campaign calendar data layer", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("serializes calendar range, filters, flags, pagination, and timezone", () => {
    expect(
      campaignCalendarQuery({
        start: "2026-09-01T00:00:00-07:00",
        end: "2026-09-30T23:59:59-07:00",
        timezone: "America/Los_Angeles",
        campaign_id: "campaign_01",
        artist_id: "artist_01",
        release_id: "release_01",
        status: "scheduled",
        event_types: ["marketing.content.scheduled", "campaign.start"],
        include_archived: false,
        include_published: true,
        limit: 250,
        offset: 25,
      }),
    ).toBe(
      "?start=2026-09-01T00%3A00%3A00-07%3A00&end=2026-09-30T23%3A59%3A59-07%3A00&timezone=America%2FLos_Angeles&campaign_id=campaign_01&artist_id=artist_01&release_id=release_01&status=scheduled&event_types=campaign.start&event_types=marketing.content.scheduled&include_archived=false&include_published=true&limit=250&offset=25",
    );
  });

  it("omits empty optional filters and keeps include flags when false", () => {
    expect(
      campaignCalendarQuery({
        start: "2026-09-01T00:00:00Z",
        end: "2026-09-30T23:59:59Z",
        timezone: "UTC",
        campaign_id: "",
        artist_id: null,
        release_id: undefined,
        event_types: [],
        include_archived: false,
        include_published: false,
      }),
    ).toBe(
      "?start=2026-09-01T00%3A00%3A00Z&end=2026-09-30T23%3A59%3A59Z&timezone=UTC&include_archived=false&include_published=false",
    );
  });

  it("uses workspace-aware range and filter-aware stable query keys", () => {
    const left = campaignCalendarQueryKeys.workspaceRange("workspace_01", {
      timezone: "America/Los_Angeles",
      start: "2026-09-01T00:00:00-07:00",
      end: "2026-09-30T23:59:59-07:00",
      event_types: ["marketing.content.scheduled", "campaign.start"],
      status: "scheduled",
    });
    const right = campaignCalendarQueryKeys.workspaceRange("workspace_01", {
      status: "scheduled",
      event_types: ["campaign.start", "marketing.content.scheduled"],
      end: "2026-09-30T23:59:59-07:00",
      start: "2026-09-01T00:00:00-07:00",
      timezone: "America/Los_Angeles",
    });

    expect(left).toBe(right);
    expect(left).toContain("workspace_01");
    expect(left).toContain("timezone:America/Los_Angeles");
    expect(left).toContain("start:2026-09-01T00:00:00-07:00");
    expect(left).toContain("end:2026-09-30T23:59:59-07:00");
    expect(
      campaignCalendarQueryKeys.workspaceRange("workspace_02", {
        timezone: "America/Los_Angeles",
        start: "2026-09-01T00:00:00-07:00",
        end: "2026-09-30T23:59:59-07:00",
      }),
    ).not.toBe(left);
  });

  it("treats comma-delimited and repeated event type filters equivalently", () => {
    const asArray = {
      start: "2026-09-01T00:00:00Z",
      end: "2026-09-30T23:59:59Z",
      timezone: "UTC",
      event_types: ["marketing.content.scheduled", "campaign.start"],
    };
    const asString = {
      ...asArray,
      event_types: "marketing.content.scheduled,campaign.start",
    };

    expect(stableCampaignCalendarQueryKey(asArray)).toBe(stableCampaignCalendarQueryKey(asString));
    expect(campaignCalendarQuery(asString)).toContain(
      "event_types=campaign.start&event_types=marketing.content.scheduled",
    );
  });

  it("does not include view mode in query keys for the same date range", () => {
    expect(
      stableCampaignCalendarQueryKey({
        start: "2026-09-01T00:00:00Z",
        end: "2026-09-30T23:59:59Z",
        timezone: "UTC",
      }),
    ).toBe("end:2026-09-30T23:59:59Z|start:2026-09-01T00:00:00Z|timezone:UTC");
  });

  it("fetches and returns backend campaign calendar events as canonical data", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({
        workspace_id: "workspace_01",
        start: "2026-09-01T00:00:00Z",
        end: "2026-09-30T23:59:59Z",
        timezone: "America/Los_Angeles",
        events: [calendarEvent],
        total: 1,
        limit: 1000,
        offset: 0,
      }),
    );

    await expect(
      listCampaignCalendarEvents("workspace_01", {
        start: "2026-09-01T00:00:00Z",
        end: "2026-09-30T23:59:59Z",
        timezone: "America/Los_Angeles",
      }),
    ).resolves.toMatchObject({
      events: [
        {
          id: "marketing_content:content_01:scheduled",
          event_type: "marketing.content.scheduled",
          approval: { request_id: "approval_01" },
        },
      ],
      total: 1,
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/campaign-calendar?start=2026-09-01T00%3A00%3A00Z&end=2026-09-30T23%3A59%3A59Z&timezone=America%2FLos_Angeles",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.any(Headers),
      }),
    );
    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("maps failed campaign calendar responses to typed errors", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        Response.json({ detail: "Invalid campaign calendar timezone" }, { status: 400 }),
      )
      .mockResolvedValueOnce(
        Response.json({ detail: "Invalid campaign calendar timezone" }, { status: 400 }),
      )
      .mockResolvedValueOnce(
        Response.json({ detail: "Invalid campaign calendar timezone" }, { status: 400 }),
      );

    await expect(
      listCampaignCalendarEvents("workspace_01", {
        start: "2026-09-01T00:00:00Z",
        end: "2026-09-30T23:59:59Z",
        timezone: "Not/AZone",
      }),
    ).rejects.toBeInstanceOf(CampaignCalendarApiError);
    await expect(
      listCampaignCalendarEvents("workspace_01", {
        start: "2026-09-01T00:00:00Z",
        end: "2026-09-30T23:59:59Z",
        timezone: "Not/AZone",
      }),
    ).rejects.toMatchObject({
      code: "validation",
      status: 400,
    });
    await expect(
      listCampaignCalendarEvents("workspace_01", {
        start: "2026-09-01T00:00:00Z",
        end: "2026-09-30T23:59:59Z",
        timezone: "Not/AZone",
      }),
    ).rejects.toThrow("Invalid campaign calendar timezone");
  });
});
