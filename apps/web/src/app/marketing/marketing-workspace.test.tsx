import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MarketingWorkspace,
  calendarVisibleRange,
  toScheduleInstances,
} from "./marketing-workspace";
import type { Campaign } from "../../lib/campaigns";
import type { MarketingContentItem } from "../../lib/marketing-content";

const replace = vi.fn();
const getParam = vi.fn<(key: string) => string | null>((key) => (key === "campaignId" ? "" : null));
let searchParamString = "";
const mutationMocks = vi.hoisted(() => ({
  create: vi.fn(),
  status: vi.fn(),
  update: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/marketing",
  useRouter: () => ({ replace }),
  useSearchParams: () => ({
    get: getParam,
    toString: () => searchParamString,
  }),
}));

vi.mock("../../lib/workspace-context", () => ({
  useActiveWorkspace: vi.fn(),
  useActiveWorkspaceProfile: vi.fn(),
}));

vi.mock("../../lib/campaigns", async () => {
  const actual = await vi.importActual<typeof import("../../lib/campaigns")>("../../lib/campaigns");
  return {
    ...actual,
    useCampaigns: vi.fn(),
  };
});

vi.mock("../../lib/marketing-content", async () => {
  const actual = await vi.importActual<typeof import("../../lib/marketing-content")>(
    "../../lib/marketing-content",
  );
  return {
    ...actual,
    useCreateMarketingContentItem: vi.fn(() => ({
      data: null,
      error: null,
      isMutating: false,
      mutate: mutationMocks.create,
      reset: vi.fn(),
    })),
    useTransitionMarketingContentStatus: vi.fn(() => ({
      data: null,
      error: null,
      isMutating: false,
      mutate: mutationMocks.status,
      reset: vi.fn(),
    })),
    useUpdateMarketingContentItem: vi.fn(() => ({
      data: null,
      error: null,
      isMutating: false,
      mutate: mutationMocks.update,
      reset: vi.fn(),
    })),
    useWorkspaceCalendarContent: vi.fn(),
  };
});

const workspaceContext = await import("../../lib/workspace-context");
const campaignsLib = await import("../../lib/campaigns");
const marketingContent = await import("../../lib/marketing-content");

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
  release: { id: "release_01", title: "Night Run", artist_id: "artist_01" },
  members: [],
  artists: [],
  releases: [],
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
};

function item(overrides: Partial<MarketingContentItem> = {}): MarketingContentItem {
  return {
    id: "content_01",
    workspace_id: "workspace_01",
    campaign_id: "campaign_01",
    title: "Single Teaser",
    content_type: "social_post",
    copy_text: "Out Friday",
    asset_refs: [],
    metadata: {},
    status: "scheduled",
    artist_id: "artist_01",
    release_id: "release_01",
    owner_profile_id: null,
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
    ...overrides,
  };
}

function channel(overrides: Partial<MarketingContentItem["channels"][number]> = {}) {
  return { ...item().channels[0]!, ...overrides };
}

function mockWorkspaceProfile(capabilityList: string[] = ["marketing.content.view"]) {
  vi.mocked(workspaceContext.useActiveWorkspace).mockReturnValue({
    activeWorkspace: {
      id: "workspace_01",
      name: "Alpha Label",
      slug: "alpha",
      role: "member",
      workspace_permission: "member",
      department_access: ["marketing"],
      capability_permissions: capabilityList,
      can_switch: true,
    },
    hasActiveWorkspace: true,
    workspaces: [],
  });
  vi.mocked(workspaceContext.useActiveWorkspaceProfile).mockReturnValue({
    capabilities: capabilityList,
    canEditProfile: false,
    departmentAccess: ["marketing"],
    isLoading: false,
    membership: {
      id: "membership_01",
      workspace_id: "workspace_01",
      status: "active",
      joined_at: "2026-09-01T12:00:00Z",
      role: "member",
      professional_roles: [],
      workspace_roles: [],
      department_access: ["marketing"],
      capability_permissions: capabilityList,
      profile: {
        id: "profile_01",
        user_id: "user_01",
        slug: "mira",
        first_name: null,
        last_name: null,
        display_name: "Mira",
        headline: null,
        biography: null,
        avatar_url: null,
        location: null,
        timezone: "America/Los_Angeles",
        primary_email: null,
        profile_status: "active",
        onboarding_status: "complete",
        links: [],
        attributes: [],
        preferences: {
          locale: "en-US",
          timezone: "America/Los_Angeles",
          default_workspace_id: "workspace_01",
          email_notifications_enabled: true,
          push_notifications_enabled: true,
          sms_notifications_enabled: false,
          marketing_notifications_enabled: false,
          interface_theme: null,
          interface_density: null,
          notification_preferences: {},
          interface_preferences: {},
          integration_preferences: {},
        },
      },
    },
    responsibilities: [],
    roles: ["member"],
    subject: {
      role: "member",
      workspacePermission: "member",
      departmentAccess: ["marketing"],
      capabilities: capabilityList,
    },
  });
}

function mockCalendar(items: MarketingContentItem[] = [item()]) {
  vi.mocked(marketingContent.useWorkspaceCalendarContent).mockReturnValue({
    data: {
      marketing_content: items,
      total: items.length,
      limit: 500,
      offset: 0,
    },
    error: null,
    isLoading: false,
    isMutating: false,
    reload: vi.fn(),
  });
}

describe("MarketingWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-15T12:00:00Z"));
    searchParamString = "";
    getParam.mockImplementation((key: string) => (key === "campaignId" ? "" : null));
    mutationMocks.create.mockResolvedValue(item({ status: "draft" }));
    mutationMocks.update.mockResolvedValue(item({ title: "Updated Teaser" }));
    mutationMocks.status.mockResolvedValue(item({ status: "in_review" }));
    mockWorkspaceProfile();
    mockCalendar();
    vi.mocked(campaignsLib.useCampaigns).mockReturnValue({
      data: { campaigns: [campaign], total: 1, limit: 500, offset: 0 },
      error: null,
      isLoading: false,
      isMutating: false,
      reload: vi.fn(),
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("calculates the visible month range including leading and trailing days", () => {
    const range = calendarVisibleRange(new Date(Date.UTC(2026, 8, 1)), "UTC");

    expect(range.gridStart.toISOString().slice(0, 10)).toBe("2026-08-30");
    expect(range.gridEnd.toISOString().slice(0, 10)).toBe("2026-10-03");
    expect(range.start).toBe("2026-08-30T00:00:00.000Z");
    expect(range.end).toBe("2026-10-03T23:59:59.000Z");
  });

  it("renders month content with one multi-channel item instead of duplicate cards", () => {
    mockCalendar([
      item({
        channels: [
          channel(),
          channel({
            id: "channel_02",
            channel: "tiktok",
            placement: "default",
            scheduled_at: "2026-09-10T20:00:00Z",
          }),
          channel({
            id: "channel_03",
            channel: "youtube",
            placement: "shorts",
            scheduled_at: "2026-09-10T20:00:00Z",
          }),
        ],
      }),
    ]);

    render(<MarketingWorkspace />);

    expect(screen.getAllByText("Single Teaser")).toHaveLength(1);
    expect(screen.getByText("Instagram • Tiktok • Youtube")).toBeInTheDocument();
    expect(screen.getByText("Multi-time")).toBeInTheDocument();
    expect(screen.getAllByText("Single Rollout").length).toBeGreaterThanOrEqual(1);
  });

  it("uses the earliest relevant channel date when the parent schedule is missing", () => {
    const instances = toScheduleInstances(
      [
        item({
          scheduled_at: null,
          channels: [
            channel({ id: "channel_01", scheduled_at: "2026-08-29T12:00:00Z" }),
            channel({ id: "channel_02", scheduled_at: "2026-09-12T12:00:00Z" }),
          ],
        }),
      ],
      "2026-08-30T00:00:00Z",
      "2026-10-03T23:59:59Z",
      "UTC",
    );

    expect(instances[0]?.scheduledAt).toBe("2026-09-12T12:00:00Z");
    expect(instances[0]?.dateKey).toBe("2026-09-12");
  });

  it("moves to previous and next month by changing the constrained query range", () => {
    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(marketingContent.useWorkspaceCalendarContent).toHaveBeenLastCalledWith(
      "workspace_01",
      expect.objectContaining({
        end: expect.stringContaining("2026-09"),
        start: expect.stringContaining("2026-07"),
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(marketingContent.useWorkspaceCalendarContent).toHaveBeenLastCalledWith(
      "workspace_01",
      expect.objectContaining({
        end: expect.stringContaining("2026-11"),
        start: expect.stringContaining("2026-09"),
      }),
    );
  });

  it("sends filters as backend query options and preserves campaign URL state", () => {
    getParam.mockImplementation((key: string) => (key === "campaignId" ? "campaign_01" : null));

    render(<MarketingWorkspace />);

    expect(marketingContent.useWorkspaceCalendarContent).toHaveBeenLastCalledWith(
      "workspace_01",
      expect.objectContaining({ campaign_id: "campaign_01" }),
    );

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "scheduled" } });
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "instagram" } });
    fireEvent.change(screen.getByLabelText("Artist"), { target: { value: "artist_01" } });
    fireEvent.change(screen.getByLabelText("Release"), { target: { value: "release_01" } });

    expect(marketingContent.useWorkspaceCalendarContent).toHaveBeenLastCalledWith(
      "workspace_01",
      expect.objectContaining({
        artist_id: "artist_01",
        campaign_id: "campaign_01",
        channel: "instagram",
        release_id: "release_01",
        status: "scheduled",
      }),
    );
    expect(replace).toHaveBeenLastCalledWith("/marketing?campaignId=campaign_01", {
      scroll: false,
    });
  });

  it("sets createDate URL state when an empty day is clicked", () => {
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);
    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Create content on 2026-09-15" }));

    expect(replace).toHaveBeenLastCalledWith("/marketing?createDate=2026-09-15", {
      scroll: false,
    });
    expect(screen.getByDisplayValue("2026-09-15T09:00")).toBeInTheDocument();
  });

  it("creates a draft with campaign, optional relationships, planned time, and channel override", async () => {
    vi.useRealTimers();
    const reload = vi.fn();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);
    vi.mocked(marketingContent.useWorkspaceCalendarContent).mockReturnValue({
      data: { marketing_content: [], total: 0, limit: 500, offset: 0 },
      error: null,
      isLoading: false,
      isMutating: false,
      reload,
    });
    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Create Content" }));
    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    fireEvent.change(within(editor).getByLabelText("Title"), { target: { value: "Launch post" } });
    fireEvent.change(within(editor).getByLabelText("Planned publish time"), {
      target: { value: "2026-09-20T10:30" },
    });
    fireEvent.change(within(editor).getByLabelText("Core Copy / Caption"), {
      target: { value: "Out now" },
    });
    fireEvent.change(within(editor).getByLabelText("Asset references"), {
      target: { value: '[{"id":"asset_01"}]' },
    });
    fireEvent.change(within(editor).getByLabelText("Channel planned publish time"), {
      target: { value: "2026-09-20T11:00" },
    });
    fireEvent.change(within(editor).getByLabelText("Channel copy override"), {
      target: { value: "IG copy" },
    });
    fireEvent.click(within(editor).getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(mutationMocks.create).toHaveBeenCalled());
    expect(mutationMocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        artist_id: "artist_01",
        asset_refs: [{ id: "asset_01" }],
        copy_text: "Out now",
        release_id: "release_01",
        title: "Launch post",
      }),
    );
    expect(mutationMocks.create.mock.calls[0]?.[0]).not.toHaveProperty("status");
    expect(mutationMocks.create.mock.calls[0]?.[0].channels).toEqual([
      expect.objectContaining({
        channel: "instagram",
        copy_text_override: "IG copy",
        placement: "feed",
        scheduled_at: expect.stringContaining("2026-09-20T"),
      }),
    ]);
    expect(reload).toHaveBeenCalled();
  });

  it("requires campaign before creating content", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);
    vi.mocked(campaignsLib.useCampaigns).mockReturnValue({
      data: { campaigns: [], total: 0, limit: 500, offset: 0 },
      error: null,
      isLoading: false,
      isMutating: false,
      reload: vi.fn(),
    });
    mockCalendar([]);
    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Create Content" }));
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Campaign is required.");
    expect(mutationMocks.create).not.toHaveBeenCalled();
  });

  it("creates content with multiple channels and optional artist/release omitted", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);
    mockCalendar([]);
    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Create Content" }));
    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    expect(within(editor).getByRole("option", { name: "Threads" })).toHaveValue("threads");
    fireEvent.change(within(editor).getByLabelText("Title"), { target: { value: "Two channels" } });
    fireEvent.change(within(editor).getByLabelText("Artist"), { target: { value: "" } });
    fireEvent.change(within(editor).getByLabelText("Release"), { target: { value: "" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Add channel" }));
    const channelSelects = within(editor).getAllByLabelText("Channel");
    const placements = within(editor).getAllByLabelText("Placement");
    fireEvent.change(channelSelects[1]!, { target: { value: "tiktok" } });
    fireEvent.change(placements[1]!, { target: { value: "clip" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(mutationMocks.create).toHaveBeenCalled());
    expect(mutationMocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        artist_id: null,
        release_id: null,
        channels: [
          expect.objectContaining({ channel: "instagram", placement: "feed" }),
          expect.objectContaining({ channel: "tiktok", placement: "clip" }),
        ],
      }),
    );
  });

  it("blocks duplicate channel and placement selections before the API call", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);
    mockCalendar([]);
    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Create Content" }));
    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    fireEvent.change(within(editor).getByLabelText("Title"), { target: { value: "Duplicate" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Add channel" }));
    const channelSelects = within(editor).getAllByLabelText("Channel");
    const placements = within(editor).getAllByLabelText("Placement");
    fireEvent.change(channelSelects[1]!, { target: { value: "instagram" } });
    fireEvent.change(placements[1]!, { target: { value: "feed" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Save draft" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Each channel and placement target can only be selected once.",
    );
    expect(mutationMocks.create).not.toHaveBeenCalled();
  });

  it("edits an existing content item with populated channel values", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.edit"]);
    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    expect(within(editor).getByDisplayValue("Single Teaser")).toBeInTheDocument();
    expect(within(editor).getByDisplayValue("feed")).toBeInTheDocument();
    fireEvent.change(within(editor).getByLabelText("Title"), {
      target: { value: "Updated Teaser" },
    });
    fireEvent.click(within(editor).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(mutationMocks.update).toHaveBeenCalled());
    expect(mutationMocks.update).toHaveBeenCalledWith(
      expect.objectContaining({
        channels: [expect.objectContaining({ channel: "instagram", placement: "feed" })],
        title: "Updated Teaser",
      }),
    );
  });

  it("submits draft content for review through the lifecycle action", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile([
      "marketing.content.view",
      "marketing.content.edit",
      "marketing.content.submit_for_review",
    ]);
    mockCalendar([item({ status: "draft" })]);
    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    fireEvent.click(screen.getByRole("button", { name: "Submit for Review" }));

    await waitFor(() => expect(mutationMocks.status).toHaveBeenCalledWith({ status: "in_review" }));
  });

  it("shows lifecycle actions based on capabilities", () => {
    mockWorkspaceProfile(["marketing.content.view"]);
    const { rerender } = render(<MarketingWorkspace />);
    expect(screen.queryByRole("button", { name: "Create Content" })).not.toBeInTheDocument();

    mockWorkspaceProfile(["marketing.content.view", "marketing.content.approve"]);
    mockCalendar([item({ status: "in_review" })]);
    rerender(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();

    mockWorkspaceProfile(["marketing.content.view"]);
    rerender(<MarketingWorkspace />);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("renders API error states from create mutations", async () => {
    vi.useRealTimers();
    mutationMocks.create.mockRejectedValueOnce(
      new marketingContent.MarketingContentApiError(
        "conflict",
        "Duplicate channel and placement target",
        409,
      ),
    );
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);
    mockCalendar([]);
    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Create Content" }));
    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    fireEvent.change(within(editor).getByLabelText("Title"), { target: { value: "API failure" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Save draft" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Duplicate channel and placement target",
    );
  });

  it("renders no-content and no-results states distinctly", () => {
    mockCalendar([]);
    const { rerender } = render(<MarketingWorkspace />);

    expect(screen.getByRole("heading", { name: "No scheduled content" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "published" } });
    rerender(<MarketingWorkspace />);

    expect(
      screen.getByRole("heading", { name: "No content matches these filters" }),
    ).toBeInTheDocument();
  });

  it("renders list view in chronological order with timezone-aware dates", () => {
    mockCalendar([
      item({
        id: "content_02",
        title: "Late LA Post",
        scheduled_at: "2026-09-11T06:30:00Z",
      }),
      item({
        id: "content_01",
        title: "Morning LA Post",
        scheduled_at: "2026-09-10T16:00:00Z",
      }),
    ]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "List" }));

    const rows = screen.getAllByRole("button", { name: /Planned/ });
    expect(within(rows[0]!).getByText("Morning LA Post")).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/Sep 10, 2026, 9:00 AM/)).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Late LA Post")).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/Sep 10, 2026, 11:30 PM/)).toBeInTheDocument();
  });

  it("renders permission denied without showing calendar content", () => {
    mockWorkspaceProfile([]);

    render(<MarketingWorkspace />);

    expect(
      screen.getByText("You need marketing content view access to open the Marketing Hub."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Single Teaser")).not.toBeInTheDocument();
  });

  it("renders loading, api-error, and permission-denied api states", () => {
    vi.mocked(marketingContent.useWorkspaceCalendarContent).mockReturnValueOnce({
      data: null,
      error: null,
      isLoading: true,
      isMutating: false,
      reload: vi.fn(),
    });
    const { rerender } = render(<MarketingWorkspace />);
    expect(screen.getByText("Loading marketing calendar")).toBeInTheDocument();

    vi.mocked(marketingContent.useWorkspaceCalendarContent).mockReturnValueOnce({
      data: null,
      error: new marketingContent.MarketingContentApiError(
        "network_failure",
        "Marketing content could not be loaded.",
      ),
      isLoading: false,
      isMutating: false,
      reload: vi.fn(),
    });
    rerender(<MarketingWorkspace />);
    expect(screen.getByRole("alert")).toHaveTextContent("Marketing content could not be loaded.");

    vi.mocked(marketingContent.useWorkspaceCalendarContent).mockReturnValueOnce({
      data: null,
      error: new marketingContent.MarketingContentApiError(
        "forbidden",
        "You do not have access to marketing content.",
      ),
      isLoading: false,
      isMutating: false,
      reload: vi.fn(),
    });
    rerender(<MarketingWorkspace />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Marketing content access was denied for these filters.",
    );
  });

  it("keeps upcoming tabs as lightweight placeholders", () => {
    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Drafts Upcoming" }));

    expect(screen.getByRole("heading", { name: "Drafts upcoming" })).toBeInTheDocument();
    expect(screen.queryByText("Single Teaser")).not.toBeInTheDocument();
  });

  it("invalidates workspace calendar queries for marketing realtime events", () => {
    expect(
      marketingContent.shouldInvalidateMarketingContentRealtimeCacheKey({
        campaignId: "campaign_01",
        contentItemId: "content_01",
        key: "marketing-content:workspace-list:workspace_01:start:2026-09-01T00:00:00Z",
        workspaceId: "workspace_01",
      }),
    ).toBe(true);
  });
});
