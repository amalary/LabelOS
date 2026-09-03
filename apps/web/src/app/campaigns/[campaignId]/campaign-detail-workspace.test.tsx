import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CampaignDetailWorkspace } from "./campaign-detail-workspace";
import type { Campaign } from "../../../lib/campaigns";
import type { MarketingContentItem } from "../../../lib/marketing-content";

vi.mock("../../../components/analytics/analytics-read-surface", () => ({
  AnalyticsReadSurface: () => <div data-testid="analytics-read-surface" />,
}));

vi.mock("../../../lib/realtime/use-organization-realtime", () => ({
  useOrganizationRealtimeContext: () => ({ recentActivityEvents: [] }),
}));

vi.mock("../../../lib/workspace-context", () => ({
  useActiveWorkspace: vi.fn(),
  useActiveWorkspaceProfile: vi.fn(),
}));

vi.mock("../../../lib/campaigns", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/campaigns")>(
    "../../../lib/campaigns",
  );
  return {
    ...actual,
    useCampaign: vi.fn(),
    useCampaignGoals: vi.fn(),
    useCampaignMilestones: vi.fn(),
  };
});

vi.mock("../../../lib/marketing-content", async () => {
  const actual =
    await vi.importActual<typeof import("../../../lib/marketing-content")>(
      "../../../lib/marketing-content",
    );
  return {
    ...actual,
    useCampaignMarketingContent: vi.fn(),
  };
});

const workspaceContext = await import("../../../lib/workspace-context");
const campaignsLib = await import("../../../lib/campaigns");
const marketingContent = await import("../../../lib/marketing-content");

const campaign: Campaign = {
  id: "campaign_01",
  workspace_id: "workspace_01",
  name: "Single Rollout",
  description: null,
  campaign_type: "release",
  status: "active",
  start_date: null,
  target_end_date: null,
  created_by_user_id: null,
  created_by_profile_id: null,
  owner_profile_id: null,
  owner: null,
  primary_artist: { id: "artist_01", name: "Mira" },
  release: null,
  members: [],
  artists: [],
  releases: [],
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
};

function contentItem(overrides: Partial<MarketingContentItem> = {}): MarketingContentItem {
  return {
    id: "content_01",
    workspace_id: "workspace_01",
    campaign_id: "campaign_01",
    title: "Launch Teaser",
    content_type: "social_post",
    copy_text: null,
    asset_refs: [],
    metadata: {},
    status: "draft",
    artist_id: null,
    release_id: null,
    owner_profile_id: null,
    created_by_user_id: null,
    created_by_profile_id: null,
    scheduled_at: null,
    published_at: null,
    approval_requested_at: null,
    approved_at: null,
    approved_by_profile_id: null,
    channels: [],
    created_at: "2026-09-01T12:00:00Z",
    updated_at: "2026-09-01T12:00:00Z",
    ...overrides,
  };
}

function resource<T>(data: T) {
  return {
    data,
    error: null,
    isLoading: false,
    isMutating: false,
    reload: vi.fn(),
  };
}

describe("CampaignDetailWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(workspaceContext.useActiveWorkspace).mockReturnValue({
      activeWorkspace: {
        id: "workspace_01",
        name: "Alpha Label",
        slug: "alpha",
        role: "member",
        workspace_permission: "member",
        department_access: ["marketing", "analytics"],
        capability_permissions: ["marketing.campaign.view", "analytics.view"],
        can_switch: true,
      },
      hasActiveWorkspace: true,
      workspaces: [],
    });
    vi.mocked(workspaceContext.useActiveWorkspaceProfile).mockReturnValue({
      capabilities: ["marketing.campaign.view", "analytics.view"],
      canEditProfile: false,
      departmentAccess: ["marketing", "analytics"],
      isLoading: false,
      membership: null,
      responsibilities: [],
      roles: ["member"],
      subject: {
        capabilities: ["marketing.campaign.view", "analytics.view"],
        departmentAccess: ["marketing", "analytics"],
        role: "member",
        workspacePermission: "member",
      },
    });
    vi.mocked(campaignsLib.useCampaign).mockReturnValue(resource(campaign));
    vi.mocked(campaignsLib.useCampaignGoals).mockReturnValue(resource({ goals: [] }));
    vi.mocked(campaignsLib.useCampaignMilestones).mockReturnValue(resource({ milestones: [] }));
    vi.mocked(marketingContent.useCampaignMarketingContent).mockReturnValue(
      resource({
        marketing_content: [
          contentItem({ id: "content_draft", status: "draft" }),
          contentItem({ id: "content_review", status: "in_review" }),
          contentItem({ id: "content_published", status: "published" }),
        ],
        total: 3,
        limit: 500,
        offset: 0,
      }),
    );
  });

  it("renders the Marketing Hub deep link and lightweight content summary", () => {
    render(<CampaignDetailWorkspace campaignId="campaign_01" />);

    expect(marketingContent.useCampaignMarketingContent).toHaveBeenCalledWith(
      "workspace_01",
      "campaign_01",
      { limit: 500, offset: 0 },
    );
    expect(screen.getByRole("link", { name: "Open Marketing" })).toHaveAttribute(
      "href",
      "/marketing?campaignId=campaign_01",
    );
    expect(screen.getByText("Content items")).toBeInTheDocument();
    expect(screen.getByText("In Review")).toBeInTheDocument();
    expect(screen.getByText("Published")).toBeInTheDocument();
  });
});
