import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CampaignApiError,
  getCampaignMembers,
  getCampaigns,
  removeCampaignMember,
  upsertCampaignMember,
} from "./campaigns";

const member = {
  workspace_membership_id: "membership_01",
  profile_id: "profile_01",
  display_name: "Mira Stone",
  participation_status: "active",
  responsibility_label: "campaign lead",
  is_owner: true,
};

const campaign = {
  id: "campaign_01",
  workspace_id: "workspace_01",
  name: "Launch Campaign",
  description: null,
  campaign_type: "marketing",
  status: "planning",
  start_date: null,
  target_end_date: null,
  created_by_user_id: "user_01",
  created_by_profile_id: "profile_01",
  owner_profile_id: "profile_01",
  owner: {
    profile_id: "profile_01",
    display_name: "Mira Stone",
  },
  members: [member],
  created_at: "2026-08-27T12:00:00Z",
  updated_at: "2026-08-27T12:00:00Z",
};

describe("campaign data layer", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("fetches campaigns through the workspace API proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ campaigns: [campaign], total: 1 }));

    await expect(getCampaigns("workspace_01")).resolves.toEqual({
      campaigns: [campaign],
      total: 1,
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/campaigns",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.any(Headers),
      }),
    );
    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("fetches campaign members with owner and responsibility metadata", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ members: [member] }));

    await expect(getCampaignMembers("workspace_01", "campaign_01")).resolves.toEqual({
      members: [member],
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/campaigns/campaign_01/members",
      expect.any(Object),
    );
  });

  it("upserts a campaign member with descriptive responsibility metadata", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(member));

    await expect(
      upsertCampaignMember("workspace_01", "campaign_01", {
        workspace_membership_id: "membership_01",
        participation_status: "active",
        responsibility_label: "campaign lead",
      }),
    ).resolves.toEqual(member);

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/campaigns/campaign_01/members",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          workspace_membership_id: "membership_01",
          participation_status: "active",
          responsibility_label: "campaign lead",
        }),
      }),
    );
    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("removes a campaign member through the workspace API proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }));

    await expect(
      removeCampaignMember("workspace_01", "campaign_01", "membership_01"),
    ).resolves.toBeUndefined();

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/campaigns/campaign_01/members/membership_01",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("maps failed campaign responses to typed errors", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "No access" }, { status: 403 }));

    await expect(getCampaigns("workspace_01")).rejects.toBeInstanceOf(CampaignApiError);
    await expect(getCampaigns("workspace_01")).rejects.toMatchObject({
      code: "forbidden",
      status: 403,
    });
  });
});
