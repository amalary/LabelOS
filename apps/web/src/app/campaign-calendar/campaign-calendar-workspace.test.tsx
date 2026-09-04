import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CampaignCalendarWorkspace,
  campaignCalendarEventHref,
} from "./campaign-calendar-workspace";
import type { CampaignCalendarEvent, CampaignCalendarResponse } from "../../lib/campaign-calendar";
import type { Campaign } from "../../lib/campaigns";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
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

vi.mock("../../lib/campaign-calendar", async () => {
  const actual = await vi.importActual<typeof import("../../lib/campaign-calendar")>(
    "../../lib/campaign-calendar",
  );
  return {
    ...actual,
    useCampaignCalendar: vi.fn(),
  };
});

const workspaceContext = await import("../../lib/workspace-context");
const campaignsLib = await import("../../lib/campaigns");
const campaignCalendar = await import("../../lib/campaign-calendar");

const campaign: Campaign = {
  id: "campaign_01",
  workspace_id: "workspace_01",
  name: "Single Rollout",
  description: null,
  campaign_type: "release",
  status: "active",
  start_date: "2026-09-10",
  target_end_date: "2026-09-30",
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

function event(overrides: Partial<CampaignCalendarEvent> = {}): CampaignCalendarEvent {
  const base: CampaignCalendarEvent = {
    id: "event_01",
    event_type: "marketing.content.scheduled",
    source_type: "marketing_content_item",
    source_id: "content_01",
    source_parent_id: "campaign_01",
    title: "Single Teaser",
    description: "Caption goes live.",
    starts_at: "2026-09-10T16:00:00Z",
    ends_at: null,
    date: null,
    all_day: false,
    timezone: "America/Los_Angeles",
    status: "scheduled",
    campaign: {
      id: "campaign_01",
      name: "Single Rollout",
      status: "active",
      campaign_type: "release",
    },
    artist: { id: "artist_01", name: "Mira" },
    release: { id: "release_01", title: "Night Run", artist_id: "artist_01" },
    channel: null,
    approval: null,
    url: null,
    sort_key: "2026-09-10T16:00:00Z|marketing.content.scheduled|content_01",
  };
  return { ...base, ...overrides };
}

function response(events: CampaignCalendarEvent[]): CampaignCalendarResponse {
  return {
    workspace_id: "workspace_01",
    start: "2026-08-30T07:00:00Z",
    end: "2026-10-04T06:59:59Z",
    timezone: "America/Los_Angeles",
    events,
    total: events.length,
    limit: 1000,
    offset: 0,
  };
}

function mockWorkspaceProfile(capabilityList: string[] = ["marketing.campaign.view"]) {
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
      capabilities: capabilityList,
      departmentAccess: ["marketing"],
    },
  });
}

function mockCampaigns() {
  vi.mocked(campaignsLib.useCampaigns).mockReturnValue({
    data: { campaigns: [campaign], total: 1, limit: 500, offset: 0 },
    error: null,
    isLoading: false,
    isMutating: false,
    reload: vi.fn(),
  });
}

function mockCalendar(events: CampaignCalendarEvent[]) {
  vi.mocked(campaignCalendar.useCampaignCalendar).mockReturnValue({
    data: response(events),
    error: null,
    isLoading: false,
    isMutating: false,
    reload: vi.fn(),
  });
}

describe("CampaignCalendarWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-15T12:00:00Z"));
    mockWorkspaceProfile();
    mockCampaigns();
    mockCalendar([event()]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the loading state", () => {
    vi.mocked(campaignCalendar.useCampaignCalendar).mockReturnValue({
      data: null,
      error: null,
      isLoading: true,
      isMutating: false,
      reload: vi.fn(),
    });

    render(<CampaignCalendarWorkspace />);

    expect(screen.getByText("Loading campaign calendar")).toBeInTheDocument();
  });

  it("renders the error state", () => {
    vi.mocked(campaignCalendar.useCampaignCalendar).mockReturnValue({
      data: null,
      error: new campaignCalendar.CampaignCalendarApiError(
        "network_failure",
        "Campaign calendar could not be loaded.",
      ),
      isLoading: false,
      isMutating: false,
      reload: vi.fn(),
    });

    render(<CampaignCalendarWorkspace />);

    expect(screen.getByRole("alert")).toHaveTextContent("Campaign calendar could not be loaded.");
  });

  it("renders empty and no-events-in-range states", () => {
    mockCalendar([]);
    const { rerender } = render(<CampaignCalendarWorkspace />);

    expect(
      screen.getByRole("heading", { name: "No campaign calendar events yet" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    rerender(<CampaignCalendarWorkspace />);

    expect(screen.getByRole("heading", { name: "No events in this range" })).toBeInTheDocument();
  });

  it("renders month view with all-day campaign, timed content, channel, and approval events", () => {
    mockCalendar([
      event({
        id: "campaign_start",
        event_type: "campaign.start",
        source_type: "campaign",
        source_id: "campaign_01",
        source_parent_id: null,
        title: "Campaign kickoff",
        starts_at: "2026-09-10T07:00:00Z",
        date: "2026-09-10",
        all_day: true,
        status: "active",
        sort_key: "2026-09-10|campaign.start|campaign_01",
      }),
      event(),
      event({
        id: "channel_01",
        event_type: "marketing.content.channel_scheduled",
        source_type: "marketing_content_channel",
        source_id: "channel_01",
        title: "TikTok cutdown",
        channel: { id: "channel_01", channel: "tiktok", placement: "feed" },
        sort_key: "2026-09-10T18:00:00Z|marketing.content.channel_scheduled|channel_01",
      }),
      event({
        id: "approval_01",
        event_type: "marketing.content.approval_requested",
        source_type: "approval_request",
        source_id: "approval_01",
        title: "Approval requested",
        approval: {
          request_id: "approval_01",
          state: "in_review",
          label: "In review",
          approved_revision_is_current: false,
          can_schedule: false,
          available_actions: [],
        },
        sort_key: "2026-09-10T19:00:00Z|marketing.content.approval_requested|approval_01",
      }),
    ]);

    render(<CampaignCalendarWorkspace />);

    const day = screen.getByRole("region", { name: "2026-09-10 events" });
    expect(
      within(day).getByRole("button", { name: "Campaign start: Campaign kickoff" }),
    ).toBeInTheDocument();
    expect(within(day).getByText("All day")).toBeInTheDocument();
    expect(
      within(day).getByRole("button", { name: "Scheduled content: Single Teaser" }),
    ).toBeInTheDocument();
    expect(
      within(day).getByRole("button", { name: "Channel schedule: TikTok cutdown" }),
    ).toBeInTheDocument();
    expect(within(day).getByText("CHAN")).toBeInTheDocument();
    expect(
      within(day).getByRole("button", { name: "Approval requested: Approval requested" }),
    ).toBeInTheDocument();
    expect(within(day).getByText("APPR")).toBeInTheDocument();
  });

  it("renders list view grouped by timezone-aware date", () => {
    mockCalendar([
      event({
        id: "late_la",
        title: "Late LA Post",
        starts_at: "2026-09-11T06:30:00Z",
        sort_key: "2026-09-11T06:30:00Z|marketing.content.scheduled|late_la",
      }),
      event({
        id: "morning_la",
        title: "Morning LA Post",
        starts_at: "2026-09-10T16:00:00Z",
        sort_key: "2026-09-10T16:00:00Z|marketing.content.scheduled|morning_la",
      }),
    ]);

    render(<CampaignCalendarWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "List" }));

    const rows = screen.getAllByRole("button", { name: /Scheduled content:/ });
    expect(within(rows[0]!).getByText("Morning LA Post")).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/Sep 10, 9:00 AM PDT/)).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Late LA Post")).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/Sep 10, 11:30 PM PDT/)).toBeInTheDocument();
  });

  it("sends filters and published/archived toggles to the campaign calendar data layer", () => {
    render(<CampaignCalendarWorkspace />);

    fireEvent.change(screen.getByLabelText("Campaign"), { target: { value: "campaign_01" } });
    fireEvent.change(screen.getByLabelText("Artist"), { target: { value: "artist_01" } });
    fireEvent.change(screen.getByLabelText("Release"), { target: { value: "release_01" } });
    fireEvent.change(screen.getByLabelText("Event type"), {
      target: { value: "marketing.content.channel_scheduled" },
    });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "scheduled" } });
    fireEvent.click(screen.getByLabelText("Include published"));
    fireEvent.click(screen.getByLabelText("Include archived"));

    expect(campaignCalendar.useCampaignCalendar).toHaveBeenLastCalledWith(
      "workspace_01",
      expect.objectContaining({
        artist_id: "artist_01",
        campaign_id: "campaign_01",
        event_types: "marketing.content.channel_scheduled",
        include_archived: true,
        include_published: true,
        release_id: "release_01",
        status: "scheduled",
        timezone: "America/Los_Angeles",
      }),
    );
  });

  it("navigates campaign events to campaigns and content or approval events to Marketing Hub", () => {
    const campaignStart = event({
      event_type: "campaign.start",
      source_type: "campaign",
      source_id: "campaign_01",
      source_parent_id: null,
      title: "Campaign kickoff",
    });
    const approval = event({
      event_type: "marketing.content.approval_requested",
      source_type: "approval_request",
      source_id: "approval_01",
      title: "Approval requested",
    });
    mockCalendar([campaignStart, approval]);

    render(<CampaignCalendarWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Campaign start: Campaign kickoff" }));
    fireEvent.click(screen.getByRole("button", { name: "Approval requested: Approval requested" }));

    expect(push).toHaveBeenNthCalledWith(1, "/campaigns/campaign_01");
    expect(push).toHaveBeenNthCalledWith(2, "/marketing?campaignId=campaign_01");
  });

  it("uses backend URLs when supplied", () => {
    expect(campaignCalendarEventHref(event({ url: "/marketing?campaignId=campaign_01" }))).toBe(
      "/marketing?campaignId=campaign_01",
    );
  });
});
