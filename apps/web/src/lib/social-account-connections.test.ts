import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  SocialAccountConnectionApiError,
  canAutoPublish,
  canReadAnalytics,
  checkSocialAccountConnectionHealth,
  createAssistedSocialAccountConnection,
  disconnectSocialAccountConnection,
  getSocialAccountConnection,
  listSocialAccountConnections,
  requiresManualPublish,
  shouldInvalidateSocialAccountConnectionRealtimeCacheKey,
  socialAccountConnectionQueryKeys,
  startSocialAccountOAuthConnection,
  syncSocialAccountConnectionMetadata,
  updateSocialAccountConnection,
  type SocialAccountConnection,
} from "./social-account-connections";

const socialAccountConnection: SocialAccountConnection = {
  id: "connection_01",
  workspace_id: "workspace_01",
  provider: "instagram",
  external_account_id: "ig-alpha-1",
  handle: "alphaartist",
  display_name: "Alpha Artist",
  profile_url: "https://instagram.com/alphaartist",
  artist_association: {
    artist_profile_id: "artist_profile_01",
    artist_id: "artist_01",
    artist_name: "Alpha Artist",
    stage_name: "Alpha",
  },
  connection_method: "assisted",
  status: "connected",
  capabilities: ["manual_publish"],
  resolved_capabilities: {
    can_auto_publish: false,
    requires_manual_publish: true,
    supports_manual_metrics: false,
    can_read_account_analytics: false,
    can_read_post_analytics: false,
  },
  token_expires_at: null,
  last_synced_at: "2026-09-05T12:00:00Z",
  last_health_checked_at: "2026-09-05T12:05:00Z",
  last_error_code: null,
  last_error_message: null,
  provider_metadata: { source: "artist-submitted" },
  created_at: "2026-09-05T12:00:00Z",
  updated_at: "2026-09-05T12:00:00Z",
};

describe("social account connections data layer", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("lists social account connections through the workspace API proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({
        social_account_connections: [socialAccountConnection],
        total: 1,
        limit: 50,
        offset: 0,
      }),
    );

    await expect(
      listSocialAccountConnections("workspace_01", {
        artist: "artist_profile_01",
        include_disconnected: false,
        limit: 50,
        provider: "instagram",
        status: "connected",
      }),
    ).resolves.toMatchObject({ total: 1 });

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/social-account-connections?include_disconnected=false&limit=50&provider=instagram&status=connected&artist_profile_id=artist_profile_01",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.any(Headers),
      }),
    );
    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("uses stable explicit query keys for social account dimensions", () => {
    expect(
      socialAccountConnectionQueryKeys.list("workspace_01", {
        artist_profile_id: "artist_profile_01",
        include_disconnected: false,
        provider: "instagram",
        status: "connected",
      }),
    ).toBe(
      "social-account-connections:list:workspace_01:artist_profile_id:artist_profile_01|include_disconnected:false|provider:instagram|status:connected",
    );
  });

  it("reads, mutates, checks, syncs, and disconnects connections through proxy routes", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(socialAccountConnection))
      .mockResolvedValueOnce(Response.json(socialAccountConnection, { status: 201 }))
      .mockResolvedValueOnce(Response.json({ ...socialAccountConnection, display_name: "Final" }))
      .mockResolvedValueOnce(Response.json({ ...socialAccountConnection, status: "connected" }))
      .mockResolvedValueOnce(Response.json({ ...socialAccountConnection, display_name: "Synced" }))
      .mockResolvedValueOnce(
        Response.json({ ...socialAccountConnection, status: "disconnected" }),
      );

    await expect(getSocialAccountConnection("workspace_01", "connection_01")).resolves.toEqual(
      socialAccountConnection,
    );
    await expect(
      createAssistedSocialAccountConnection("workspace_01", {
        artist_profile_id: "artist_profile_01",
        display_name: "Alpha Artist",
        handle: "@AlphaArtist",
        profile_url: "https://instagram.com/AlphaArtist",
        provider: "Instagram",
      }),
    ).resolves.toEqual(socialAccountConnection);
    await expect(
      updateSocialAccountConnection("workspace_01", "connection_01", {
        artist_profile_id: null,
        display_name: "Final",
      }),
    ).resolves.toMatchObject({ display_name: "Final" });
    await expect(
      checkSocialAccountConnectionHealth("workspace_01", "connection_01"),
    ).resolves.toMatchObject({ status: "connected" });
    await expect(
      syncSocialAccountConnectionMetadata("workspace_01", "connection_01"),
    ).resolves.toMatchObject({ display_name: "Synced" });
    await expect(
      disconnectSocialAccountConnection("workspace_01", "connection_01"),
    ).resolves.toMatchObject({ status: "disconnected" });

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/workspaces/workspace_01/social-account-connections/connection_01",
      expect.any(Object),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/workspaces/workspace_01/social-account-connections",
      expect.objectContaining({
        body: expect.stringContaining('"provider":"Instagram"'),
        method: "POST",
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      "/api/workspaces/workspace_01/social-account-connections/connection_01",
      expect.objectContaining({
        body: expect.stringContaining('"artist_profile_id":null'),
        method: "PATCH",
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      4,
      "/api/workspaces/workspace_01/social-account-connections/connection_01/health",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      5,
      "/api/workspaces/workspace_01/social-account-connections/connection_01/sync",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      6,
      "/api/workspaces/workspace_01/social-account-connections/connection_01/disconnect",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("starts OAuth social account connections through the workspace proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({
        authorization_url: "https://accounts.example/authorize?state=state_01",
        state: "state_01",
        expires_at: "2026-09-06T12:10:00Z",
        scopes: ["publish"],
      }),
    );

    await expect(
      startSocialAccountOAuthConnection("workspace_01", {
        provider: "youtube",
        redirect_uri:
          "https://app.labelos.test/api/workspaces/workspace_01/social-account-connections/oauth/youtube/callback",
        scopes: ["publish"],
      }),
    ).resolves.toMatchObject({ state: "state_01" });

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/social-account-connections/oauth/start",
      expect.objectContaining({
        body: expect.stringContaining('"provider":"youtube"'),
        method: "POST",
      }),
    );
  });

  it("derives frontend capability helpers from resolved capabilities and capability keys", () => {
    expect(canAutoPublish(socialAccountConnection)).toBe(false);
    expect(requiresManualPublish(socialAccountConnection)).toBe(true);
    expect(canReadAnalytics(socialAccountConnection)).toBe(false);

    const directConnection = {
      ...socialAccountConnection,
      capabilities: ["content_publish", "account_analytics_read"],
      resolved_capabilities: {
        ...socialAccountConnection.resolved_capabilities,
        can_auto_publish: true,
        can_read_account_analytics: true,
        requires_manual_publish: false,
      },
    };

    expect(canAutoPublish(directConnection)).toBe(true);
    expect(requiresManualPublish(directConnection)).toBe(false);
    expect(canReadAnalytics(directConnection)).toBe(true);
  });

  it("targets social account caches from realtime connection events", () => {
    const shouldInvalidate = (key: string) =>
      shouldInvalidateSocialAccountConnectionRealtimeCacheKey({
        connectionId: "connection_01",
        key,
        workspaceId: "workspace_01",
      });

    expect(shouldInvalidate("social-account-connections:list:workspace_01:default")).toBe(true);
    expect(
      shouldInvalidate("social-account-connections:detail:workspace_01:connection_01"),
    ).toBe(true);
    expect(shouldInvalidate("social-account-connections:list:workspace_02:default")).toBe(false);
    expect(
      shouldInvalidate("social-account-connections:detail:workspace_01:connection_02"),
    ).toBe(false);
  });

  it("maps failed social account connection responses to typed errors", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "No access" }, { status: 403 }));

    await expect(listSocialAccountConnections("workspace_01")).rejects.toBeInstanceOf(
      SocialAccountConnectionApiError,
    );
    await expect(listSocialAccountConnections("workspace_01")).rejects.toMatchObject({
      code: "forbidden",
      status: 403,
    });
  });
});
