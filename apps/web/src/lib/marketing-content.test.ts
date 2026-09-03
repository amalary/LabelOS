import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  MarketingContentApiError,
  archiveMarketingContentItem,
  createMarketingContentItem,
  getMarketingContentItem,
  listCampaignContent,
  listWorkspaceCalendarContent,
  marketingContentQueryKeys,
  shouldInvalidateMarketingContentRealtimeCacheKey,
  transitionMarketingContentStatus,
  updateMarketingContentItem,
} from "./marketing-content";

const marketingContentItem = {
  id: "content_01",
  workspace_id: "workspace_01",
  campaign_id: "campaign_01",
  title: "Announcement post",
  content_type: "social_post",
  copy_text: "Out Friday",
  asset_refs: [],
  metadata: {},
  status: "draft",
  artist_id: "artist_01",
  release_id: null,
  owner_profile_id: "profile_01",
  created_by_user_id: "user_01",
  created_by_profile_id: "profile_01",
  scheduled_at: "2026-09-10T12:00:00Z",
  published_at: null,
  approval_requested_at: null,
  approved_at: null,
  approved_by_profile_id: null,
  channels: [
    {
      id: "channel_01",
      marketing_content_item_id: "content_01",
      channel: "instagram",
      placement: "feed",
      scheduled_at: "2026-09-10T12:00:00Z",
      published_at: null,
      external_post_id: null,
      external_url: null,
      copy_text_override: null,
      asset_refs: [],
      metadata: {},
      created_at: "2026-09-01T12:00:00Z",
      updated_at: "2026-09-01T12:00:00Z",
    },
  ],
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
} as const;

describe("marketing content data layer", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("lists workspace calendar content through the workspace API proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ marketing_content: [marketingContentItem], total: 1, limit: 100, offset: 0 }),
    );

    await expect(
      listWorkspaceCalendarContent("workspace_01", {
        start: "2026-09-01T00:00:00Z",
        end: "2026-09-30T23:59:59Z",
        campaign: "campaign_01",
        artist: "artist_01",
        release: "release_01",
        status: "draft",
        channel: "instagram",
      }),
    ).resolves.toMatchObject({ total: 1 });

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/marketing-content?start=2026-09-01T00%3A00%3A00Z&end=2026-09-30T23%3A59%3A59Z&status=draft&channel=instagram&campaign_id=campaign_01&artist_id=artist_01&release_id=release_01",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.any(Headers),
      }),
    );
  });

  it("uses stable explicit query keys for calendar dimensions", () => {
    expect(
      marketingContentQueryKeys.workspaceList("workspace_01", {
        channel: "instagram",
        status: "draft",
        start: "2026-09-01T00:00:00Z",
        end: "2026-09-30T23:59:59Z",
      }),
    ).toBe(
      "marketing-content:workspace-list:workspace_01:channel:instagram|end:2026-09-30T23:59:59Z|start:2026-09-01T00:00:00Z|status:draft",
    );
  });

  it("reads and mutates campaign-scoped content through proxy routes", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        Response.json({
          marketing_content: [marketingContentItem],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      )
      .mockResolvedValueOnce(Response.json(marketingContentItem))
      .mockResolvedValueOnce(Response.json(marketingContentItem, { status: 201 }))
      .mockResolvedValueOnce(Response.json({ ...marketingContentItem, title: "Updated" }))
      .mockResolvedValueOnce(Response.json({ ...marketingContentItem, status: "archived" }))
      .mockResolvedValueOnce(Response.json({ ...marketingContentItem, status: "in_review" }));

    await expect(
      listCampaignContent("workspace_01", "campaign_01", { limit: 50 }),
    ).resolves.toMatchObject({
      total: 1,
    });
    await expect(
      getMarketingContentItem("workspace_01", "campaign_01", "content_01"),
    ).resolves.toEqual(marketingContentItem);
    await expect(
      createMarketingContentItem("workspace_01", "campaign_01", {
        title: "Announcement post",
        content_type: "social_post",
      }),
    ).resolves.toEqual(marketingContentItem);
    await expect(
      updateMarketingContentItem("workspace_01", "campaign_01", "content_01", {
        title: "Updated",
      }),
    ).resolves.toMatchObject({ title: "Updated" });
    await expect(
      archiveMarketingContentItem("workspace_01", "campaign_01", "content_01"),
    ).resolves.toMatchObject({ status: "archived" });
    await expect(
      transitionMarketingContentStatus("workspace_01", "campaign_01", "content_01", {
        status: "in_review",
      }),
    ).resolves.toMatchObject({ status: "in_review" });

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/workspaces/workspace_01/campaigns/campaign_01/marketing-content?limit=50",
      expect.any(Object),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/workspaces/workspace_01/campaigns/campaign_01/marketing-content/content_01",
      expect.any(Object),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      "/api/workspaces/workspace_01/campaigns/campaign_01/marketing-content",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      4,
      "/api/workspaces/workspace_01/campaigns/campaign_01/marketing-content/content_01",
      expect.objectContaining({ method: "PATCH" }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      5,
      "/api/workspaces/workspace_01/campaigns/campaign_01/marketing-content/content_01/archive",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      6,
      "/api/workspaces/workspace_01/campaigns/campaign_01/marketing-content/content_01/status",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("targets marketing content caches from realtime content events", () => {
    const shouldInvalidate = (key: string) =>
      shouldInvalidateMarketingContentRealtimeCacheKey({
        campaignId: "campaign_01",
        contentItemId: "content_01",
        key,
        workspaceId: "workspace_01",
      });

    expect(shouldInvalidate("marketing-content:workspace-list:workspace_01:default")).toBe(true);
    expect(
      shouldInvalidate("marketing-content:campaign-list:workspace_01:campaign_01:default"),
    ).toBe(true);
    expect(shouldInvalidate("marketing-content:detail:workspace_01:campaign_01:content_01")).toBe(
      true,
    );
    expect(shouldInvalidate("marketing-content:workspace-list:workspace_02:default")).toBe(false);
    expect(
      shouldInvalidate("marketing-content:campaign-list:workspace_01:campaign_02:default"),
    ).toBe(false);
    expect(shouldInvalidate("marketing-content:detail:workspace_01:campaign_01:content_02")).toBe(
      false,
    );
  });

  it("maps failed marketing content responses to typed errors", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "No access" }, { status: 403 }));

    await expect(listWorkspaceCalendarContent("workspace_01")).rejects.toBeInstanceOf(
      MarketingContentApiError,
    );
    await expect(listWorkspaceCalendarContent("workspace_01")).rejects.toMatchObject({
      code: "forbidden",
      status: 403,
    });
  });
});
