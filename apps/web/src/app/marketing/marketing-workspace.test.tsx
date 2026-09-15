import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MarketingWorkspace, toScheduleInstances } from "./marketing-workspace";
import type {
  ApprovalAction,
  ApprovalRequestDetail,
  ApprovalRequestList,
  ApprovalRequestSummary,
} from "../../lib/approvals";
import type { Campaign } from "../../lib/campaigns";
import type { MarketingContentItem } from "../../lib/marketing-content";
import type {
  SocialAccountConnection,
  SocialAccountConnectionsList,
} from "../../lib/social-account-connections";

const replace = vi.fn();
const getParam = vi.fn<(key: string) => string | null>((key) => (key === "campaignId" ? "" : null));
let searchParamString = "";
const mutationMocks = vi.hoisted(() => ({
  approvalDecision: vi.fn(),
  approvalSubmit: vi.fn(),
  archive: vi.fn(),
  create: vi.fn(),
  socialCreate: vi.fn(),
  socialDisconnect: vi.fn(),
  socialNavigate: vi.fn(),
  socialOAuthStart: vi.fn(),
  socialUpdate: vi.fn(),
  status: vi.fn(),
  update: vi.fn(),
}));
const approvalHookState = vi.hoisted(() => ({
  detail: null as ApprovalRequestDetail | null,
  detailError: null as Error | null,
  detailLoading: false,
  queue: null as ApprovalRequestList | null,
  queueError: null as Error | null,
  queueLoading: false,
  submittedOptions: [] as unknown[],
}));
const realtimeHookState = vi.hoisted(() => ({
  recentActivityEvents: [] as Array<{
    id: string;
    type: string;
    createdAt: string;
    actor: null;
    entityType: string;
    entityId: string;
    payload: Record<string, unknown>;
  }>,
}));
const contentHookState = vi.hoisted(() => ({
  archiveError: null as InstanceType<typeof Error> | null,
  archiveMutating: false,
  calendarItems: [] as MarketingContentItem[],
  detailData: null as MarketingContentItem | null,
  detailError: null as InstanceType<typeof Error> | null,
  detailLoading: false,
  draftItems: [] as MarketingContentItem[],
  detailReload: vi.fn(),
}));
const socialHookState = vi.hoisted(() => ({
  createError: null as Error | null,
  createMutating: false,
  disconnectError: null as Error | null,
  disconnectMutating: false,
  list: null as SocialAccountConnectionsList | null,
  listError: null as Error | null,
  listLoading: false,
  oauthStartError: null as Error | null,
  oauthStartMutating: false,
  listReload: vi.fn(),
  updateError: null as Error | null,
  updateMutating: false,
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
    useArchiveMarketingContentItem: vi.fn(() => ({
      data: null,
      error: contentHookState.archiveError,
      isMutating: contentHookState.archiveMutating,
      mutate: mutationMocks.archive,
      reset: vi.fn(),
    })),
    useCreateMarketingContentItem: vi.fn(() => ({
      data: null,
      error: null,
      isMutating: false,
      mutate: mutationMocks.create,
      reset: vi.fn(),
    })),
    useMarketingContentItem: vi.fn(
      (_workspaceId: string | null, campaignId: string | null, contentItemId: string | null) => {
        const selected =
          contentHookState.detailData ??
          [...contentHookState.calendarItems, ...contentHookState.draftItems].find(
            (entry) =>
              entry.id === contentItemId && (!campaignId || entry.campaign_id === campaignId),
          ) ??
          null;
        return {
          data: contentHookState.detailError || contentHookState.detailLoading ? null : selected,
          error: contentHookState.detailError,
          isLoading: contentHookState.detailLoading,
          isMutating: false,
          reload: contentHookState.detailReload,
        };
      },
    ),
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
    useWorkspaceMarketingContent: vi.fn(),
  };
});

vi.mock("../../lib/approvals", async () => {
  const actual = await vi.importActual<typeof import("../../lib/approvals")>("../../lib/approvals");
  return {
    ...actual,
    useApprovalDecision: vi.fn(
      (_workspaceId: string | null, _approvalRequestId: string | null, action: ApprovalAction) => ({
        data: null,
        error: null,
        isMutating: false,
        mutate: (payload: unknown) =>
          mutationMocks.approvalDecision({
            action,
            ...(payload && typeof payload === "object" ? payload : {}),
          }),
        reset: vi.fn(),
      }),
    ),
    useApprovalQueue: vi.fn((_workspaceId: string | null, options: unknown) => {
      approvalHookState.submittedOptions.push(options);
      return {
        data: approvalHookState.queue,
        error: approvalHookState.queueError,
        isLoading: approvalHookState.queueLoading,
        isMutating: false,
        reload: vi.fn(),
      };
    }),
    useApprovalRequest: vi.fn(() => ({
      data: approvalHookState.detail,
      error: approvalHookState.detailError,
      isLoading: approvalHookState.detailLoading,
      isMutating: false,
      reload: vi.fn().mockResolvedValue(approvalHookState.detail),
    })),
    useSubmitMarketingContentForApproval: vi.fn(() => ({
      data: null,
      error: null,
      isMutating: false,
      mutate: mutationMocks.approvalSubmit,
      reset: vi.fn(),
    })),
  };
});

vi.mock("../../lib/social-account-connections", async () => {
  const actual = await vi.importActual<typeof import("../../lib/social-account-connections")>(
    "../../lib/social-account-connections",
  );
  return {
    ...actual,
    navigateToSocialAccountAuthorization: mutationMocks.socialNavigate,
    useCreateAssistedSocialAccountConnection: vi.fn(() => ({
      data: null,
      error: socialHookState.createError,
      isMutating: socialHookState.createMutating,
      mutate: mutationMocks.socialCreate,
      reset: vi.fn(),
    })),
    useDisconnectSocialAccountConnection: vi.fn(() => ({
      data: null,
      error: socialHookState.disconnectError,
      isMutating: socialHookState.disconnectMutating,
      mutate: mutationMocks.socialDisconnect,
      reset: vi.fn(),
    })),
    useSocialAccountConnections: vi.fn(() => ({
      data: socialHookState.listLoading || socialHookState.listError ? null : socialHookState.list,
      error: socialHookState.listError,
      isLoading: socialHookState.listLoading,
      isMutating: false,
      reload: socialHookState.listReload,
    })),
    useStartSocialAccountOAuthConnection: vi.fn(() => ({
      data: null,
      error: socialHookState.oauthStartError,
      isMutating: socialHookState.oauthStartMutating,
      mutate: mutationMocks.socialOAuthStart,
      reset: vi.fn(),
    })),
    useUpdateSocialAccountConnection: vi.fn(() => ({
      data: null,
      error: socialHookState.updateError,
      isMutating: socialHookState.updateMutating,
      mutate: mutationMocks.socialUpdate,
      reset: vi.fn(),
    })),
  };
});

vi.mock("../../lib/realtime/use-organization-realtime", () => ({
  useOrganizationRealtimeContext: () => ({
    connectionState: "connected",
    lastUpdatedBy: null,
    organizationId: "workspace_01",
    presence: [],
    recentActivityEvents: realtimeHookState.recentActivityEvents,
  }),
}));

const workspaceContext = await import("../../lib/workspace-context");
const approvalsLib = await import("../../lib/approvals");
const campaignsLib = await import("../../lib/campaigns");
const marketingContent = await import("../../lib/marketing-content");
const socialAccounts = await import("../../lib/social-account-connections");

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
  const base: MarketingContentItem = {
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
    approval_request_id: null,
    approval_state: {
      approval_request_id: null,
      approved_revision: null,
      approved_revision_is_current: false,
      can_schedule: false,
      current_revision: 1,
      label: "Scheduled",
      state: "scheduled",
    },
    content_revision: 1,
    approved_revision: null,
    approved_at: null,
    approved_by_profile_id: null,
    channels: [
      {
        id: "channel_01",
        marketing_content_item_id: "content_01",
        channel: "instagram",
        placement: "feed",
        social_account_connection_id: null,
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
  };
  const merged = { ...base, ...overrides };
  if (!overrides.approval_state) {
    merged.approval_state = {
      approval_request_id: merged.approval_request_id,
      approved_revision: merged.approved_revision,
      approved_revision_is_current:
        merged.approved_revision !== null && merged.approved_revision === merged.content_revision,
      can_schedule:
        merged.status === "approved" &&
        merged.approved_revision !== null &&
        merged.approved_revision === merged.content_revision,
      current_revision: merged.content_revision,
      label: humanizedStatus(merged.status),
      state: merged.status,
    };
  }
  return merged;
}

function humanizedStatus(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function channel(overrides: Partial<MarketingContentItem["channels"][number]> = {}) {
  return { ...item().channels[0]!, ...overrides };
}

function destinationReadiness(
  overrides: Partial<
    NonNullable<MarketingContentItem["channels"][number]["destination_readiness"]>
  > = {},
): NonNullable<MarketingContentItem["channels"][number]["destination_readiness"]> {
  return {
    account: {
      connection_method: "direct_api",
      display_name: "Mira Official",
      handle: "@mira",
      id: "connection_01",
      provider: "instagram",
      status: "connected",
    },
    delivery_ready: true,
    label: "Ready",
    planning_valid: true,
    status: "ready",
    warning: null,
    ...overrides,
  };
}

function socialConnection(
  overrides: Partial<SocialAccountConnection> = {},
): SocialAccountConnection {
  const base: SocialAccountConnection = {
    artist_association: {
      artist_id: "artist_01",
      artist_name: "Mira",
      artist_profile_id: "artist_profile_01",
      stage_name: "Mira",
    },
    capabilities: ["manual_publish"],
    connection_method: "assisted",
    created_at: "2026-09-05T12:00:00Z",
    display_name: "Mira Official",
    external_account_id: null,
    handle: "@mira",
    id: "connection_01",
    last_error_code: null,
    last_error_message: null,
    last_health_checked_at: "2026-09-05T12:05:00Z",
    last_synced_at: null,
    profile_url: "https://instagram.com/mira",
    provider: "instagram",
    provider_metadata: { source: "artist-submitted" },
    resolved_capabilities: {
      can_auto_publish: false,
      can_read_account_analytics: false,
      can_read_post_analytics: false,
      requires_manual_publish: true,
      supports_manual_metrics: false,
    },
    status: "connected",
    token_expires_at: null,
    updated_at: "2026-09-05T12:00:00Z",
    workspace_id: "workspace_01",
  };
  return { ...base, ...overrides };
}

function mockSocialAccounts(connections: SocialAccountConnection[] = []) {
  socialHookState.list = {
    limit: 100,
    offset: 0,
    social_account_connections: connections,
    total: connections.length,
  };
  socialHookState.listError = null;
  socialHookState.listLoading = false;
}

function mockSocialAccountsLoading() {
  socialHookState.list = null;
  socialHookState.listError = null;
  socialHookState.listLoading = true;
}

function mockSocialAccountsError(error: Error) {
  socialHookState.list = null;
  socialHookState.listError = error;
  socialHookState.listLoading = false;
}

function approvalSummary(overrides: Partial<ApprovalRequestSummary> = {}): ApprovalRequestSummary {
  return {
    artist: { id: "artist_01", name: "Mira" },
    campaign: { id: "campaign_01", name: "Single Rollout" },
    current_stage: {
      assigned_profile_id: "profile_01",
      completed_at: null,
      id: "stage_01",
      required_capability: "marketing.content.approve",
      stage_order: 1,
      started_at: "2026-09-01T12:10:00Z",
      status: "in_review",
    },
    id: "approval_01",
    resource_id: "content_01",
    resource_type: "marketing_content_item",
    resolved_at: null,
    stage_assignment: {
      display_name: "Mira",
      profile_id: "profile_01",
      user_id: "user_01",
    },
    status: "in_review",
    submitted_at: "2026-09-01T12:00:00Z",
    submitted_revision: 2,
    submitter: {
      display_name: "Sam",
      profile_id: "profile_02",
      user_id: "user_02",
    },
    summary: "Please review the launch caption.",
    title: "Single Teaser",
    workspace_id: "workspace_01",
    ...overrides,
  };
}

function approvalDetail(overrides: Partial<ApprovalRequestDetail> = {}): ApprovalRequestDetail {
  return {
    ...approvalSummary(),
    available_actions: ["approved", "changes_requested", "rejected", "cancelled"],
    channels: [{ channel: "instagram", placement: "feed" }],
    current_resource_revision: 2,
    decision_history: [
      {
        actor_key: "user_02",
        actor_kind: "user",
        created_at: "2026-09-01T12:00:00Z",
        decided_by_profile_id: "profile_02",
        decided_by_user_id: "user_02",
        decision: "submitted",
        id: "decision_01",
        payload: { checklist: { brand_safe: true } },
        reason: "Ready for review",
        stage_id: "stage_01",
      },
    ],
    is_stale: false,
    marketing_content_preview: {
      approved_revision: null,
      asset_refs: [],
      content_type: "social_post",
      copy_text: "Out Friday",
      current_revision: 2,
      id: "content_01",
      status: "in_review",
      title: "Single Teaser",
    },
    release: { id: "release_01", name: "Night Run" },
    ...overrides,
  };
}

function mockApprovalQueue(
  approvals: ApprovalRequestSummary[] = [],
  overrides: Partial<ApprovalRequestList> = {},
) {
  approvalHookState.queue = {
    approvals,
    limit: 50,
    offset: 0,
    total: approvals.length,
    ...overrides,
  };
  approvalHookState.queueError = null;
  approvalHookState.queueLoading = false;
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
  contentHookState.calendarItems = items;
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

function mockDrafts(items: MarketingContentItem[] = [item({ status: "draft" })], reload = vi.fn()) {
  contentHookState.draftItems = items;
  vi.mocked(marketingContent.useWorkspaceMarketingContent).mockReturnValue({
    data: {
      marketing_content: items,
      total: items.length,
      limit: 500,
      offset: 0,
    },
    error: null,
    isLoading: false,
    isMutating: false,
    reload,
  });
}

function mockDraftsLoading() {
  contentHookState.draftItems = [];
  vi.mocked(marketingContent.useWorkspaceMarketingContent).mockReturnValue({
    data: null,
    error: null,
    isLoading: true,
    isMutating: false,
    reload: vi.fn(),
  });
}

function mockDraftsError(
  error = new marketingContent.MarketingContentApiError("network_failure", "Failed"),
) {
  contentHookState.draftItems = [];
  vi.mocked(marketingContent.useWorkspaceMarketingContent).mockReturnValue({
    data: null,
    error,
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
    approvalHookState.detail = approvalDetail();
    approvalHookState.detailError = null;
    approvalHookState.detailLoading = false;
    approvalHookState.queue = { approvals: [], total: 0, limit: 50, offset: 0 };
    approvalHookState.queueError = null;
    approvalHookState.queueLoading = false;
    approvalHookState.submittedOptions = [];
    contentHookState.calendarItems = [];
    contentHookState.archiveError = null;
    contentHookState.archiveMutating = false;
    contentHookState.detailData = null;
    contentHookState.detailError = null;
    contentHookState.detailLoading = false;
    contentHookState.draftItems = [];
    contentHookState.detailReload = vi.fn();
    socialHookState.createError = null;
    socialHookState.createMutating = false;
    socialHookState.disconnectError = null;
    socialHookState.disconnectMutating = false;
    socialHookState.listError = null;
    socialHookState.listLoading = false;
    socialHookState.listReload = vi.fn();
    socialHookState.oauthStartError = null;
    socialHookState.oauthStartMutating = false;
    socialHookState.updateError = null;
    socialHookState.updateMutating = false;
    realtimeHookState.recentActivityEvents = [];
    vi.mocked(approvalsLib.useApprovalDecision).mockImplementation(
      (_workspaceId: string | null, _approvalRequestId: string | null, action: ApprovalAction) => ({
        data: null,
        error: null,
        isMutating: false,
        mutate: (payload: unknown) =>
          mutationMocks.approvalDecision({
            action,
            ...(payload && typeof payload === "object" ? payload : {}),
          }),
        reset: vi.fn(),
      }),
    );
    mutationMocks.approvalDecision.mockResolvedValue(approvalDetail());
    mutationMocks.approvalSubmit.mockResolvedValue(approvalDetail());
    mutationMocks.archive.mockResolvedValue(item({ status: "archived" }));
    mutationMocks.create.mockResolvedValue(item({ status: "draft" }));
    mutationMocks.socialCreate.mockResolvedValue(socialConnection());
    mutationMocks.socialDisconnect.mockResolvedValue(socialConnection({ status: "disconnected" }));
    mutationMocks.socialOAuthStart.mockResolvedValue({
      authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?state=state_01",
      expires_at: "2026-09-07T12:10:00Z",
      scopes: ["https://www.googleapis.com/auth/youtube.readonly"],
      state: "state_01",
    });
    mutationMocks.socialUpdate.mockResolvedValue(socialConnection({ display_name: "Mira Final" }));
    mutationMocks.update.mockResolvedValue(item({ title: "Updated Teaser" }));
    mutationMocks.status.mockResolvedValue(item({ status: "in_review" }));
    mockWorkspaceProfile();
    mockCalendar();
    mockDrafts();
    mockSocialAccounts();
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
    vi.unstubAllEnvs();
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
    expect(screen.getByText("Instagram / Tiktok / Youtube")).toBeInTheDocument();
    expect(screen.getByText("Multi-time")).toBeInTheDocument();
    expect(screen.getAllByText("Single Rollout").length).toBeGreaterThanOrEqual(1);
  });

  it("shows destination readiness on calendar channel rows without blocking planning", () => {
    mockCalendar([
      item({
        channels: [
          channel({
            destination_readiness: destinationReadiness(),
            social_account_connection_id: "connection_auto",
          }),
          channel({
            channel: "tiktok",
            destination_readiness: destinationReadiness({
              account: {
                connection_method: "assisted",
                display_name: "Mira TikTok",
                handle: "@mira",
                id: "connection_assisted",
                provider: "tiktok",
                status: "connected",
              },
              label: "Assisted Publishing",
              status: "assisted",
              warning: "Delivery requires assisted publishing.",
            }),
            id: "channel_02",
            social_account_connection_id: "connection_assisted",
          }),
          channel({
            channel: "youtube",
            destination_readiness: destinationReadiness({
              account: {
                connection_method: "direct_api",
                display_name: "Mira YouTube",
                handle: "@mira",
                id: "connection_reconnect",
                provider: "youtube",
                status: "reconnect_required",
              },
              delivery_ready: false,
              label: "Reconnect Required",
              status: "reconnect_required",
              warning: "Selected account must be reconnected before delivery.",
            }),
            id: "channel_03",
            social_account_connection_id: "connection_reconnect",
          }),
          channel({
            channel: "facebook",
            destination_readiness: destinationReadiness({
              account: null,
              delivery_ready: false,
              label: "No Account Selected",
              status: "missing_account",
              warning: "Missing account is a delivery warning; content planning remains valid.",
            }),
            id: "channel_04",
            social_account_connection_id: null,
          }),
          channel({
            channel: "x",
            destination_readiness: destinationReadiness({
              account: {
                connection_method: "direct_api",
                display_name: "Mira X",
                handle: "@mira_x",
                id: "connection_disconnected",
                provider: "x",
                status: "disconnected",
              },
              delivery_ready: false,
              label: "Disconnected",
              status: "disconnected",
              warning: "Selected account is disconnected; choose another account before delivery.",
            }),
            id: "channel_05",
            social_account_connection_id: "connection_disconnected",
          }),
        ],
      }),
    ]);

    render(<MarketingWorkspace />);

    expect(screen.getByText("Instagram @mira Ready")).toBeInTheDocument();
    expect(screen.getByText("Tiktok @mira Assisted Publishing")).toBeInTheDocument();
    expect(screen.getByText("Youtube @mira Reconnect Required")).toBeInTheDocument();
    expect(screen.getByText("Facebook No Account Selected")).toBeInTheDocument();
    expect(screen.getByText("X @mira_x Disconnected")).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Submit for approval" }));

    await waitFor(() =>
      expect(mutationMocks.approvalSubmit).toHaveBeenCalledWith({
        expected_resource_revision: 1,
      }),
    );
    expect(mutationMocks.status).not.toHaveBeenCalled();
  });

  it("shows approval compatibility states on calendar items and opens their queue review", () => {
    mockWorkspaceProfile([
      "marketing.content.view",
      "marketing.content.edit",
      "marketing.content.submit_for_review",
    ]);
    mockCalendar([
      item({
        approval_request_id: "approval_01",
        approval_state: {
          approval_request_id: "approval_01",
          approved_revision: null,
          approved_revision_is_current: false,
          can_schedule: false,
          current_revision: 1,
          label: "In review",
          state: "in_review",
        },
        status: "in_review",
      }),
      item({
        id: "content_02",
        title: "Change Copy",
        approval_request_id: "approval_02",
        approval_state: {
          approval_request_id: "approval_02",
          approved_revision: null,
          approved_revision_is_current: false,
          can_schedule: false,
          current_revision: 1,
          label: "Changes requested",
          state: "changes_requested",
        },
        status: "draft",
      }),
      item({
        id: "content_03",
        title: "Edited Approved",
        approval_state: {
          approval_request_id: null,
          approved_revision: 1,
          approved_revision_is_current: false,
          can_schedule: false,
          current_revision: 2,
          label: "Reapproval required",
          state: "reapproval_required",
        },
        approved_revision: 1,
        content_revision: 2,
        status: "draft",
      }),
    ]);

    render(<MarketingWorkspace />);

    expect(screen.getByText("In review")).toBeInTheDocument();
    expect(screen.getByText("Changes requested")).toBeInTheDocument();
    expect(screen.getByText("Reapproval required")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    fireEvent.click(screen.getByRole("button", { name: "Open Approval Review" }));

    expect(screen.getByRole("region", { name: "Approval review detail" })).toBeInTheDocument();
  });

  it("schedules only approved current revisions and blocks stale approved revisions", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.edit"]);
    mockCalendar([
      item({
        approval_request_id: "approval_01",
        approval_state: {
          approval_request_id: "approval_01",
          approved_revision: 2,
          approved_revision_is_current: true,
          can_schedule: true,
          current_revision: 2,
          label: "Approved",
          state: "approved",
        },
        approved_revision: 2,
        content_revision: 2,
        status: "approved",
      }),
    ]);
    mutationMocks.status.mockResolvedValueOnce(item({ status: "scheduled" }));

    const { rerender } = render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    fireEvent.click(screen.getByRole("button", { name: "Schedule" }));

    await waitFor(() => expect(mutationMocks.status).toHaveBeenCalledWith({ status: "scheduled" }));

    mockCalendar([
      item({
        approval_state: {
          approval_request_id: null,
          approved_revision: 1,
          approved_revision_is_current: false,
          can_schedule: false,
          current_revision: 2,
          label: "Reapproval required",
          state: "reapproval_required",
        },
        approved_revision: 1,
        content_revision: 2,
        status: "approved",
        updated_at: "2026-09-02T12:00:00Z",
      }),
    ]);
    rerender(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));

    expect(screen.getByRole("button", { name: "Schedule" })).toBeDisabled();
    expect(screen.getByText(/Scheduling is blocked/)).toBeInTheDocument();
  });

  it("hides approved scheduling actions without the edit capability", () => {
    mockWorkspaceProfile(["marketing.content.view"]);
    mockCalendar([
      item({
        approval_request_id: "approval_01",
        approval_state: {
          approval_request_id: "approval_01",
          approved_revision: 2,
          approved_revision_is_current: true,
          can_schedule: true,
          current_revision: 2,
          label: "Approved",
          state: "approved",
        },
        approved_revision: 2,
        content_revision: 2,
        status: "approved",
      }),
    ]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    const editor = screen.getByRole("region", { name: "Marketing content editor" });

    expect(within(editor).queryByRole("button", { name: "Schedule" })).not.toBeInTheDocument();
    expect(within(editor).queryByText(/Scheduling is blocked/)).not.toBeInTheDocument();
    expect(
      within(editor).getByText("You need edit access to change this content."),
    ).toBeInTheDocument();
  });

  it("warns before material edits to currently approved content", async () => {
    vi.useRealTimers();
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.edit"]);
    mockCalendar([
      item({
        approval_state: {
          approval_request_id: "approval_01",
          approved_revision: 1,
          approved_revision_is_current: true,
          can_schedule: true,
          current_revision: 1,
          label: "Approved",
          state: "approved",
        },
        approval_request_id: "approval_01",
        approved_revision: 1,
        content_revision: 1,
        status: "approved",
      }),
    ]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Approved Edit" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(confirm).toHaveBeenCalled();
    expect(mutationMocks.update).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(mutationMocks.update).toHaveBeenCalled());
  });

  it("shows lifecycle actions based on capabilities", () => {
    mockWorkspaceProfile(["marketing.content.view"]);
    const { rerender } = render(<MarketingWorkspace />);
    expect(screen.queryByRole("button", { name: "Create Content" })).not.toBeInTheDocument();

    mockWorkspaceProfile(["marketing.content.view"]);
    mockCalendar([item({ approval_request_id: "approval_01", status: "in_review" })]);
    rerender(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    expect(screen.getByRole("button", { name: "Open Approval Review" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();

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

  it("enables the approvals tab and loads an empty marketing content queue", () => {
    mockApprovalQueue([]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));

    expect(screen.getByRole("heading", { name: "Approval Queue" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No approvals in this queue" })).toBeInTheDocument();
    expect(approvalHookState.submittedOptions.at(-1)).toMatchObject({
      assigned_to_me: true,
      resource_type: "marketing_content_item",
      status: "in_review",
    });
  });

  it("opens directly to a focused approval from navigation query params", () => {
    getParam.mockImplementation((key: string) => {
      if (key === "tab") {
        return "approvals";
      }
      if (key === "approvalRequestId") {
        return "approval_01";
      }
      return null;
    });
    mockApprovalQueue([approvalSummary()]);
    approvalHookState.detail = approvalDetail();

    render(<MarketingWorkspace />);

    expect(screen.getByRole("heading", { name: "Approval Queue" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Approval review detail" })).toHaveTextContent(
      "Request approval_01",
    );
  });

  it("renders queue results and sends each queue filter to the approval API", () => {
    mockApprovalQueue([approvalSummary()]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));

    expect(screen.getByText("Please review the launch caption.")).toBeInTheDocument();
    expect(screen.getByText("Submitter: Sam")).toBeInTheDocument();
    expect(screen.getByText("Reviewer: Mira")).toBeInTheDocument();
    expect(screen.getByText("Action required")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Submitted by me" }));
    expect(approvalHookState.submittedOptions.at(-1)).toMatchObject({
      resource_type: "marketing_content_item",
      submitted_by_me: true,
    });

    fireEvent.click(screen.getByRole("tab", { name: "Changes requested" }));
    expect(approvalHookState.submittedOptions.at(-1)).toMatchObject({
      resource_type: "marketing_content_item",
      status: "changes_requested",
    });

    fireEvent.click(screen.getByRole("tab", { name: "Approved" }));
    expect(approvalHookState.submittedOptions.at(-1)).toMatchObject({
      resource_type: "marketing_content_item",
      status: "approved",
    });

    fireEvent.click(screen.getByRole("tab", { name: "Rejected" }));
    expect(approvalHookState.submittedOptions.at(-1)).toMatchObject({
      resource_type: "marketing_content_item",
      status: "rejected",
    });

    fireEvent.click(screen.getByRole("tab", { name: "All" }));
    expect(approvalHookState.submittedOptions.at(-1)).toMatchObject({
      resource_type: "marketing_content_item",
    });
    expect(approvalHookState.submittedOptions.at(-1)).not.toHaveProperty("status");
  });

  it("renders review detail with preview, context, history, and calendar navigation", () => {
    mockApprovalQueue([approvalSummary()]);
    approvalHookState.detail = approvalDetail();
    mockCalendar([item({ status: "in_review" })]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));

    const detail = screen.getByRole("region", { name: "Approval review detail" });
    expect(within(detail).getByText("Out Friday")).toBeInTheDocument();
    expect(within(detail).getByText("Single Rollout")).toBeInTheDocument();
    expect(within(detail).getByText("Night Run")).toBeInTheDocument();
    expect(within(detail).getByText("Instagram / Feed")).toBeInTheDocument();
    expect(within(detail).getByText("Ready for review")).toBeInTheDocument();
    expect(within(detail).getByText(/brand_safe/)).toBeInTheDocument();

    fireEvent.click(within(detail).getByRole("button", { name: "Open calendar item" }));
    expect(screen.getByRole("region", { name: "Marketing content editor" })).toBeInTheDocument();
  });

  it("shows only server-provided available actions", () => {
    mockApprovalQueue([approvalSummary()]);
    approvalHookState.detail = approvalDetail({ available_actions: ["approved"] });

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));

    const detail = screen.getByRole("region", { name: "Approval review detail" });
    expect(within(detail).getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(
      within(detail).queryByRole("button", { name: "Request changes" }),
    ).not.toBeInTheDocument();
    expect(within(detail).queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(
      within(detail).queryByRole("button", { name: "Cancel request" }),
    ).not.toBeInTheDocument();
  });

  it("submits approve decisions through the generic approval action", async () => {
    vi.useRealTimers();
    mockApprovalQueue([approvalSummary()]);
    approvalHookState.detail = approvalDetail({ available_actions: ["approved"] });

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(mutationMocks.approvalDecision).toHaveBeenCalledWith(
        expect.objectContaining({ action: "approved", reason: null }),
      ),
    );
  });

  it("requires comments for requested changes and rejection", () => {
    mockApprovalQueue([approvalSummary()]);
    approvalHookState.detail = approvalDetail({
      available_actions: ["changes_requested", "rejected"],
    });

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    fireEvent.click(screen.getByRole("button", { name: "Request changes" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "A reason is required for rejection and requested changes.",
    );
    expect(mutationMocks.approvalDecision).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(mutationMocks.approvalDecision).not.toHaveBeenCalled();
  });

  it("submits requested changes and rejection with required reasons", async () => {
    vi.useRealTimers();
    mockApprovalQueue([approvalSummary()]);
    approvalHookState.detail = approvalDetail({
      available_actions: ["changes_requested", "rejected"],
    });

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    fireEvent.change(screen.getByLabelText("Reason or feedback"), {
      target: { value: "Tighten the caption." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request changes" }));

    await waitFor(() =>
      expect(mutationMocks.approvalDecision).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "changes_requested",
          reason: "Tighten the caption.",
        }),
      ),
    );

    fireEvent.change(screen.getByLabelText("Reason or feedback"), {
      target: { value: "Wrong campaign." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));

    await waitFor(() =>
      expect(mutationMocks.approvalDecision).toHaveBeenCalledWith(
        expect.objectContaining({ action: "rejected", reason: "Wrong campaign." }),
      ),
    );
  });

  it("disables decision controls while a mutation is pending", () => {
    vi.mocked(approvalsLib.useApprovalDecision).mockImplementation(
      (_workspaceId: string | null, _approvalRequestId: string | null, action: ApprovalAction) => ({
        data: null,
        error: null,
        isMutating: action === "approved",
        mutate: mutationMocks.approvalDecision,
        reset: vi.fn(),
      }),
    );
    mockApprovalQueue([approvalSummary()]);
    approvalHookState.detail = approvalDetail();

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));

    expect(screen.getByRole("button", { name: "Approving..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Request changes" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });

  it("clearly represents stale approval requests", () => {
    mockApprovalQueue([approvalSummary()]);
    approvalHookState.detail = approvalDetail({
      current_resource_revision: 4,
      is_stale: true,
      submitted_revision: 2,
    });

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));

    expect(screen.getByText("Stale approval")).toBeInTheDocument();
    expect(screen.getByText(/submitted for revision 2/)).toBeInTheDocument();
    expect(screen.getByText(/current content revision is 4/)).toBeInTheDocument();
  });

  it("renders unauthorized approval queue state", () => {
    approvalHookState.queue = null;
    approvalHookState.queueError = new approvalsLib.ApprovalApiError(
      "unauthorized",
      "Sign in again to load approvals.",
      401,
    );

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));

    expect(screen.getByRole("status")).toHaveTextContent("Sign in again to load approvals.");
  });

  it("shows resolved approval state without decision controls", () => {
    mockApprovalQueue([
      approvalSummary({ resolved_at: "2026-09-02T12:00:00Z", status: "approved" }),
    ]);
    approvalHookState.detail = approvalDetail({
      available_actions: [],
      resolved_at: "2026-09-02T12:00:00Z",
      status: "approved",
    });

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));

    expect(screen.getByText("Resolved")).toBeInTheDocument();
    expect(screen.getByText("No approval actions are currently available.")).toBeInTheDocument();
  });

  it("shows realtime approval refresh activity in the queue", () => {
    realtimeHookState.recentActivityEvents = [
      {
        actor: null,
        createdAt: "2026-09-03T12:00:00Z",
        entityId: "approval_01",
        entityType: "approval_request",
        id: "event_01",
        payload: {},
        type: "approval.updated",
      },
    ];

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));

    expect(screen.getByText(/Realtime refresh: approval.updated/)).toBeInTheDocument();
  });

  it("enables the drafts tab and renders draft posts from marketing content", () => {
    mockDrafts([
      item({ id: "content_draft_01", status: "draft", title: "Draft Caption" }),
      item({ id: "content_scheduled_01", status: "scheduled", title: "Scheduled Caption" }),
    ]);

    render(<MarketingWorkspace />);

    const draftsTab = screen.getByRole("button", { name: "Drafts" });
    expect(draftsTab).toBeEnabled();

    fireEvent.click(draftsTab);

    expect(screen.getByRole("region", { name: "Draft posts" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Draft Posts" })).toBeInTheDocument();
    expect(screen.getByText("Draft Caption")).toBeInTheDocument();
    expect(screen.queryByText("Scheduled Caption")).not.toBeInTheDocument();
    expect(marketingContent.useWorkspaceMarketingContent).toHaveBeenLastCalledWith(
      "workspace_01",
      expect.objectContaining({ limit: 500, offset: 0, status: "draft" }),
    );
  });

  it("shows the drafts empty state with a create action", () => {
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);
    mockDrafts([]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));

    expect(screen.getByRole("heading", { name: "No draft posts" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Draft posts appear here before they are submitted for approval or scheduled.",
      ),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create Draft" }));
    expect(screen.getByRole("region", { name: "Marketing content editor" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Create draft post" })).toBeInTheDocument();
  });

  it("creates a channel-aware draft from Draft Posts with the existing marketing content mutation", async () => {
    vi.useRealTimers();
    const calendarReload = vi.fn();
    const draftsReload = vi.fn();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);
    vi.mocked(marketingContent.useWorkspaceCalendarContent).mockReturnValue({
      data: { marketing_content: [], total: 0, limit: 500, offset: 0 },
      error: null,
      isLoading: false,
      isMutating: false,
      reload: calendarReload,
    });
    mockDrafts(
      [item({ id: "content_draft_01", status: "draft", title: "Existing Draft" })],
      draftsReload,
    );
    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Draft" }));
    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    expect(within(editor).getByLabelText("Planned publish time")).toBeInTheDocument();
    expect(within(editor).getByLabelText("Channel planned publish time")).toBeInTheDocument();

    fireEvent.change(within(editor).getByLabelText("Title"), {
      target: { value: "Channel-aware launch draft" },
    });
    fireEvent.change(within(editor).getByLabelText("Planned publish time"), {
      target: { value: "2026-09-10T09:00" },
    });
    fireEvent.change(within(editor).getByLabelText("Core Copy / Caption"), {
      target: { value: "Presave starts now." },
    });
    fireEvent.change(within(editor).getByLabelText("Asset references"), {
      target: { value: '[{"id":"asset_draft_01","type":"image"}]' },
    });
    fireEvent.change(within(editor).getByLabelText("Channel copy override"), {
      target: { value: "IG draft copy" },
    });
    fireEvent.change(within(editor).getByLabelText("Channel planned publish time"), {
      target: { value: "2026-09-10T10:30" },
    });
    fireEvent.click(within(editor).getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(mutationMocks.create).toHaveBeenCalled());
    expect(mutationMocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        artist_id: "artist_01",
        asset_refs: [{ id: "asset_draft_01", type: "image" }],
        content_type: "social_post",
        copy_text: "Presave starts now.",
        release_id: "release_01",
        scheduled_at: "2026-09-10T16:00:00Z",
        title: "Channel-aware launch draft",
      }),
    );
    expect(mutationMocks.create.mock.calls[0]?.[0]).not.toHaveProperty("status");
    expect(mutationMocks.create.mock.calls[0]?.[0].channels).toEqual([
      expect.objectContaining({
        channel: "instagram",
        copy_text_override: "IG draft copy",
        placement: "feed",
        scheduled_at: "2026-09-10T17:30:00Z",
      }),
    ]);
    expect(mutationMocks.approvalSubmit).not.toHaveBeenCalled();
    expect(mutationMocks.status).not.toHaveBeenCalled();
    expect(calendarReload).toHaveBeenCalled();
    await waitFor(() => expect(draftsReload).toHaveBeenCalled());
  });

  it("creates a multi-channel draft with channel overrides from Draft Posts", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Draft" }));
    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    fireEvent.change(within(editor).getByLabelText("Title"), {
      target: { value: "Multi-channel draft" },
    });
    fireEvent.click(within(editor).getByRole("button", { name: "Add channel" }));

    const channelSelects = within(editor).getAllByLabelText("Channel");
    const placements = within(editor).getAllByLabelText("Placement");
    const plannedTimes = within(editor).getAllByLabelText("Channel planned publish time");
    const overrides = within(editor).getAllByLabelText("Channel copy override");
    const channelAssets = within(editor).getAllByLabelText("Channel asset references");
    fireEvent.change(placements[0]!, { target: { value: "reel" } });
    fireEvent.change(plannedTimes[0]!, { target: { value: "2026-09-10T11:00" } });
    fireEvent.change(overrides[0]!, { target: { value: "IG-specific cut" } });
    fireEvent.change(channelAssets[0]!, {
      target: { value: '[{"id":"ig_asset","type":"video"}]' },
    });
    fireEvent.change(channelSelects[1]!, { target: { value: "tiktok" } });
    fireEvent.change(placements[1]!, { target: { value: "video" } });
    fireEvent.change(plannedTimes[1]!, { target: { value: "2026-09-10T12:00" } });
    fireEvent.change(overrides[1]!, { target: { value: "TikTok-specific cut" } });
    fireEvent.change(channelAssets[1]!, {
      target: { value: '[{"id":"tt_asset","type":"video"}]' },
    });

    fireEvent.click(within(editor).getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(mutationMocks.create).toHaveBeenCalled());
    expect(mutationMocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        channels: [
          expect.objectContaining({
            asset_refs: [{ id: "ig_asset", type: "video" }],
            channel: "instagram",
            copy_text_override: "IG-specific cut",
            placement: "reel",
            scheduled_at: "2026-09-10T18:00:00Z",
          }),
          expect.objectContaining({
            asset_refs: [{ id: "tt_asset", type: "video" }],
            channel: "tiktok",
            copy_text_override: "TikTok-specific cut",
            placement: "video",
            scheduled_at: "2026-09-10T19:00:00Z",
          }),
        ],
        title: "Multi-channel draft",
      }),
    );
  });

  it.each(["earlier", "later"] as const)(
    "requires an explicit %s DST occurrence and retains invalid input",
    async (choice) => {
      vi.useRealTimers();
      mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);
      render(<MarketingWorkspace />);
      fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
      fireEvent.click(screen.getByRole("button", { name: "Create Draft" }));
      const editor = within(screen.getByRole("region", { name: "Marketing content editor" }));
      fireEvent.change(editor.getByLabelText("Title"), { target: { value: "DST launch" } });
      fireEvent.change(editor.getByLabelText("Channel authoring timezone"), {
        target: { value: "America/New_York" },
      });
      fireEvent.change(editor.getByLabelText("Channel planned publish time"), {
        target: { value: "2026-03-08T02:30" },
      });
      fireEvent.click(editor.getByRole("button", { name: "Save draft" }));
      expect(mutationMocks.create).not.toHaveBeenCalled();
      expect(editor.getByLabelText("Channel planned publish time")).toHaveValue("2026-03-08T02:30");
      expect(
        editor.getAllByRole("alert").some((alert) => alert.textContent?.includes("does not exist")),
      ).toBe(true);
      fireEvent.change(editor.getByLabelText("Channel planned publish time"), {
        target: { value: "2026-11-01T01:30" },
      });
      fireEvent.click(editor.getByRole("button", { name: "Save draft" }));
      expect(mutationMocks.create).not.toHaveBeenCalled();
      expect(editor.getByLabelText("Schedule occurrence")).toHaveValue("");
      fireEvent.change(editor.getByLabelText("Schedule occurrence"), { target: { value: choice } });
      fireEvent.click(editor.getByRole("button", { name: "Save draft" }));
      await waitFor(() => expect(mutationMocks.create).toHaveBeenCalled());
      expect(mutationMocks.create.mock.calls[0]?.[0].channels[0]).toMatchObject({
        scheduled_at: choice === "earlier" ? "2026-11-01T05:30:00Z" : "2026-11-01T06:30:00Z",
        schedule_timezone: "America/New_York",
        schedule_disambiguation: choice,
      });
    },
  );

  it("retains authoring input after a server validation error", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);
    mutationMocks.create.mockRejectedValueOnce(
      new Error("The timestamp does not match the selected local time and timezone."),
    );
    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Draft" }));
    const editor = within(screen.getByRole("region", { name: "Marketing content editor" }));
    fireEvent.change(editor.getByLabelText("Title"), { target: { value: "Keep this draft" } });
    fireEvent.change(editor.getByLabelText("Channel authoring timezone"), {
      target: { value: "America/New_York" },
    });
    fireEvent.change(editor.getByLabelText("Channel planned publish time"), {
      target: { value: "2027-06-15T09:30" },
    });
    fireEvent.click(editor.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(editor.getByRole("alert")).toHaveTextContent("does not match"));
    expect(editor.getByLabelText("Title")).toHaveValue("Keep this draft");
    expect(editor.getByLabelText("Channel authoring timezone")).toHaveValue("America/New_York");
    expect(editor.getByLabelText("Channel planned publish time")).toHaveValue("2027-06-15T09:30");
  });

  it("preserves legacy timestamps on an unchanged save without guessing their timezone", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.edit"]);
    mockCalendar([item()]);
    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    const editor = within(screen.getByRole("region", { name: "Marketing content editor" }));
    expect(editor.getByLabelText("Channel authoring timezone")).toHaveValue("");
    expect(
      editor.getByText(/Legacy planning time shown in America\/Los_Angeles/),
    ).toBeInTheDocument();
    fireEvent.click(editor.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(mutationMocks.update).toHaveBeenCalled());
    expect(mutationMocks.update.mock.calls[0]?.[0].channels[0]).toMatchObject({
      id: "channel_01",
      scheduled_at: "2026-09-10T12:00:00Z",
    });
    expect(mutationMocks.update.mock.calls[0]?.[0].channels[0]).not.toHaveProperty(
      "schedule_timezone",
    );
  });

  it("edits a persisted authoring timezone independently of the calendar display zone", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.edit"]);
    mockCalendar([
      item({
        channels: [
          channel({
            schedule_timezone: "America/New_York",
            schedule_local_time: "2026-09-10T08:00:00",
            schedule_offset_seconds: -14400,
          }),
        ],
      }),
    ]);
    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: /Single Teaser/ }));
    const editor = within(screen.getByRole("region", { name: "Marketing content editor" }));
    expect(editor.getByLabelText("Channel authoring timezone")).toHaveValue("America/New_York");
    expect(editor.getByLabelText("Channel planned publish time")).toHaveValue("2026-09-10T08:00");
    fireEvent.click(editor.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(mutationMocks.update).toHaveBeenCalled());
    expect(mutationMocks.update.mock.calls[0]?.[0].channels[0]).toMatchObject({
      id: "channel_01",
      scheduled_at: "2026-09-10T12:00:00Z",
      schedule_timezone: "America/New_York",
    });
  });

  it("shows Draft Posts validation errors before creating", () => {
    vi.useRealTimers();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Title is required.");
    expect(mutationMocks.create).not.toHaveBeenCalled();
  });

  it("shows Draft Posts API errors from the existing create mutation", async () => {
    vi.useRealTimers();
    mutationMocks.create.mockRejectedValueOnce(
      new marketingContent.MarketingContentApiError(
        "validation",
        "Marketing content has validation errors.",
        422,
      ),
    );
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Draft" }));
    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    fireEvent.change(within(editor).getByLabelText("Title"), {
      target: { value: "Rejected draft" },
    });
    fireEvent.click(within(editor).getByRole("button", { name: "Save draft" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Marketing content has validation errors.",
    );
  });

  it("loads a canonical draft detail and updates it with the existing marketing content mutation", async () => {
    vi.useRealTimers();
    const calendarReload = vi.fn();
    const draftsReload = vi.fn();
    const draft = item({
      asset_refs: [{ id: "asset_existing" }],
      channels: [
        channel({
          asset_refs: [{ id: "channel_asset_existing" }],
          copy_text_override: "Existing IG copy",
          placement: "reels",
        }),
      ],
      content_revision: 3,
      copy_text: "Existing draft copy",
      id: "content_draft_01",
      status: "draft",
      title: "Draft Caption",
      updated_at: "2026-09-12T10:30:00Z",
    });
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.edit"]);
    vi.mocked(marketingContent.useWorkspaceCalendarContent).mockReturnValue({
      data: { marketing_content: [], total: 0, limit: 500, offset: 0 },
      error: null,
      isLoading: false,
      isMutating: false,
      reload: calendarReload,
    });
    mockDrafts([draft], draftsReload);
    mutationMocks.update.mockResolvedValueOnce(
      item({
        ...draft,
        content_revision: 4,
        copy_text: "Updated canonical copy",
        title: "Updated Draft Caption",
      }),
    );

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Open draft Draft Caption" }));

    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    expect(marketingContent.useMarketingContentItem).toHaveBeenLastCalledWith(
      "workspace_01",
      "campaign_01",
      "content_draft_01",
    );
    expect(within(editor).getByDisplayValue("Draft Caption")).toBeInTheDocument();
    expect(within(editor).getByDisplayValue("Existing draft copy")).toBeInTheDocument();
    expect(within(editor).getByDisplayValue("reels")).toBeInTheDocument();
    expect(within(editor).getByDisplayValue("Existing IG copy")).toBeInTheDocument();
    expect(
      within(editor).getByText("Current status: Draft - Approval: Draft - Revision 3"),
    ).toBeInTheDocument();

    fireEvent.change(within(editor).getByLabelText("Title"), {
      target: { value: "Updated Draft Caption" },
    });
    fireEvent.change(within(editor).getByLabelText("Core Copy / Caption"), {
      target: { value: "Updated canonical copy" },
    });
    fireEvent.change(within(editor).getByLabelText("Asset references"), {
      target: { value: '[{"id":"asset_updated"}]' },
    });
    fireEvent.change(within(editor).getByLabelText("Channel copy override"), {
      target: { value: "Updated IG copy" },
    });
    fireEvent.click(within(editor).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(mutationMocks.update).toHaveBeenCalled());
    expect(mutationMocks.update).toHaveBeenCalledWith(
      expect.objectContaining({
        asset_refs: [{ id: "asset_updated" }],
        channels: [
          expect.objectContaining({
            asset_refs: [{ id: "channel_asset_existing" }],
            id: draft.channels[0]!.id,
            channel: "instagram",
            copy_text_override: "Updated IG copy",
            placement: "reels",
          }),
        ],
        copy_text: "Updated canonical copy",
        title: "Updated Draft Caption",
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Saved Updated Draft Caption. Revision 4.",
    );
    expect(calendarReload).toHaveBeenCalled();
    await waitFor(() => expect(draftsReload).toHaveBeenCalled());
  });

  it("shows the draft detail loading state after selecting a draft", () => {
    const draft = item({ id: "content_draft_01", status: "draft", title: "Draft Caption" });
    contentHookState.detailLoading = true;
    mockDrafts([draft]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Open draft Draft Caption" }));

    expect(screen.getByRole("status")).toHaveTextContent("Loading marketing content detail");
  });

  it("shows missing or deleted draft detail state", () => {
    const draft = item({ id: "content_draft_01", status: "draft", title: "Draft Caption" });
    contentHookState.detailError = new marketingContent.MarketingContentApiError(
      "not_found",
      "Marketing content was not found.",
      404,
    );
    mockDrafts([draft]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Open draft Draft Caption" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "This marketing content is missing or was deleted.",
    );
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("shows draft detail authorization failure without rendering edit controls", () => {
    const draft = item({ id: "content_draft_01", status: "draft", title: "Draft Caption" });
    contentHookState.detailError = new marketingContent.MarketingContentApiError(
      "forbidden",
      "You do not have access to marketing content.",
      403,
    );
    mockDrafts([draft]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Open draft Draft Caption" }));

    expect(screen.getByRole("status")).toHaveTextContent(
      "You do not have access to this marketing content.",
    );
    expect(screen.queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
  });

  it("shows validation failures from draft detail saves", async () => {
    vi.useRealTimers();
    const draft = item({ id: "content_draft_01", status: "draft", title: "Draft Caption" });
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.edit"]);
    mockDrafts([draft]);
    mutationMocks.update.mockRejectedValueOnce(
      new marketingContent.MarketingContentApiError(
        "validation",
        "Channel asset references must be a JSON array.",
        422,
      ),
    );

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Open draft Draft Caption" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Channel asset references must be a JSON array.",
    );
  });

  it("shows save failures from draft detail saves", async () => {
    vi.useRealTimers();
    const draft = item({ id: "content_draft_01", status: "draft", title: "Draft Caption" });
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.edit"]);
    mockDrafts([draft]);
    mutationMocks.update.mockRejectedValueOnce(
      new marketingContent.MarketingContentApiError(
        "network_failure",
        "Unable to reach the marketing content API.",
      ),
    );

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Open draft Draft Caption" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to reach the marketing content API.",
    );
  });

  it("shows the drafts loading state", () => {
    mockDraftsLoading();

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));

    expect(screen.getByRole("status")).toHaveTextContent("Loading draft posts");
  });

  it("shows the drafts error state", () => {
    mockDraftsError();

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Draft posts could not be loaded.");
  });

  it("shows the drafts forbidden error state", () => {
    mockDraftsError(
      new marketingContent.MarketingContentApiError(
        "forbidden",
        "You do not have access to draft posts.",
      ),
    );

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Marketing content access was denied for drafts.",
    );
  });

  it("renders populated draft rows with existing marketing content metadata", () => {
    mockDrafts([
      item({
        approval_state: {
          approval_request_id: "approval_02",
          approved_revision: 1,
          approved_revision_is_current: false,
          can_schedule: false,
          current_revision: 3,
          label: "Changes requested",
          state: "changes_requested",
        },
        approved_revision: 1,
        channels: [
          channel({ channel: "instagram", placement: "reels" }),
          channel({ channel: "tiktok", placement: "video" }),
        ],
        content_revision: 3,
        content_type: "short_video",
        copy_text: "Behind the scenes clip for release week.",
        created_by_profile_id: "profile_creator",
        id: "content_draft_01",
        owner_profile_id: "profile_owner",
        status: "draft",
        title: "BTS Draft",
        updated_at: "2026-09-12T10:30:00Z",
      }),
    ]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));

    expect(screen.getByText("BTS Draft")).toBeInTheDocument();
    expect(screen.getByText("Behind the scenes clip for release week.")).toBeInTheDocument();
    expect(screen.getByText("Short Video - Instagram / Tiktok")).toBeInTheDocument();
    expect(screen.getAllByText("Single Rollout").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Artist: artist_01")).toBeInTheDocument();
    expect(screen.getByText("Release: release_01")).toBeInTheDocument();
    expect(screen.getByText("Instagram / Reels, Tiktok / Video")).toBeInTheDocument();
    expect(screen.getByText("Revision 3 / approved 1")).toBeInTheDocument();
    expect(screen.getByText("Changes requested")).toBeInTheDocument();
    expect(screen.getByText("2026-09-12")).toBeInTheDocument();
    expect(screen.getByText("Owner profile_owner")).toBeInTheDocument();
  });

  it("resubmits returned draft content with the current revision from Draft Posts", async () => {
    vi.useRealTimers();
    const draft = item({
      approval_request_id: "approval_02",
      approval_state: {
        approval_request_id: "approval_02",
        approved_revision: null,
        approved_revision_is_current: false,
        can_schedule: false,
        current_revision: 3,
        label: "Changes requested",
        state: "changes_requested",
      },
      content_revision: 3,
      id: "content_draft_02",
      status: "draft",
      title: "Returned Draft",
    });
    mockWorkspaceProfile([
      "marketing.content.view",
      "marketing.content.edit",
      "marketing.content.submit_for_review",
    ]);
    mockDrafts([draft]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));

    expect(screen.getByText("Changes requested")).toBeInTheDocument();
    expect(screen.getByText("Revision 3")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open draft Returned Draft" }));
    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    expect(
      within(editor).getByText("Current status: Draft - Approval: Changes requested - Revision 3"),
    ).toBeInTheDocument();

    fireEvent.click(within(editor).getByRole("button", { name: "Resubmit for approval" }));

    await waitFor(() =>
      expect(mutationMocks.approvalSubmit).toHaveBeenCalledWith({
        expected_resource_revision: 3,
      }),
    );
  });

  it("submits eligible draft rows through the existing approval request action", async () => {
    vi.useRealTimers();
    const draftsReload = vi.fn();
    const draft = item({
      content_revision: 5,
      id: "content_draft_03",
      status: "draft",
      title: "Row Submit Draft",
    });
    mockWorkspaceProfile([
      "marketing.content.view",
      "marketing.content.edit",
      "marketing.content.submit_for_review",
    ]);
    mockDrafts([draft], draftsReload);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Submit for approval Row Submit Draft" }));

    await waitFor(() =>
      expect(mutationMocks.approvalSubmit).toHaveBeenCalledWith({
        expected_resource_revision: 5,
      }),
    );
    expect(mutationMocks.status).not.toHaveBeenCalled();
    expect(draftsReload).toHaveBeenCalled();
  });

  it("hides draft row submission without the submit-for-review capability", () => {
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.edit"]);
    mockDrafts([item({ id: "content_draft_04", status: "draft", title: "No Submit Draft" })]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));

    expect(
      screen.queryByRole("button", { name: "Submit for approval No Submit Draft" }),
    ).not.toBeInTheDocument();
  });

  it("archives a draft row after confirmation and removes it from active Draft Posts", async () => {
    vi.useRealTimers();
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(true);
    const calendarReload = vi.fn().mockResolvedValue({ marketing_content: [], total: 0 });
    const draftsReload = vi.fn().mockResolvedValue({ marketing_content: [], total: 0 });
    const draft = item({
      id: "content_abandoned",
      status: "draft",
      title: "Abandoned Draft",
    });
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.archive"]);
    vi.mocked(marketingContent.useWorkspaceCalendarContent).mockReturnValue({
      data: { marketing_content: [], total: 0, limit: 500, offset: 0 },
      error: null,
      isLoading: false,
      isMutating: false,
      reload: calendarReload,
    });
    mockDrafts([draft], draftsReload);
    mutationMocks.archive.mockResolvedValueOnce(item({ ...draft, status: "archived" }));

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Archive draft Abandoned Draft" }));

    expect(confirm).toHaveBeenCalledWith(
      'Archive "Abandoned Draft"? It will be hidden from active Draft Posts and retained in Marketing Content history.',
    );
    await waitFor(() => expect(mutationMocks.archive).toHaveBeenCalled());
    expect(marketingContent.useArchiveMarketingContentItem).toHaveBeenCalledWith(
      "workspace_01",
      "campaign_01",
      "content_abandoned",
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Open draft Abandoned Draft" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("status")).toHaveTextContent("Archived Abandoned Draft.");
    expect(draftsReload).toHaveBeenCalled();
    expect(calendarReload).toHaveBeenCalled();
  });

  it("cancels draft archive when confirmation is declined", () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.archive"]);
    mockDrafts([item({ id: "content_keep", status: "draft", title: "Keep Draft" })]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Archive draft Keep Draft" }));

    expect(confirm).toHaveBeenCalled();
    expect(mutationMocks.archive).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Open draft Keep Draft" })).toBeInTheDocument();
  });

  it("enforces archive authorization in Draft Posts actions", () => {
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.edit"]);
    mockDrafts([item({ id: "content_no_archive", status: "draft", title: "No Archive Draft" })]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));

    expect(
      screen.queryByRole("button", { name: "Archive draft No Archive Draft" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open draft No Archive Draft" }));
    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    expect(within(editor).queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
  });

  it("surfaces draft archive API failures clearly", async () => {
    vi.useRealTimers();
    vi.spyOn(window, "confirm").mockReturnValueOnce(true);
    contentHookState.archiveError = new marketingContent.MarketingContentApiError(
      "forbidden",
      "You do not have archive access for marketing content.",
      403,
    );
    mutationMocks.archive.mockRejectedValueOnce(contentHookState.archiveError);
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.archive"]);
    mockDrafts([item({ id: "content_denied", status: "draft", title: "Denied Draft" })]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Archive draft Denied Draft" }));

    await waitFor(() => expect(mutationMocks.archive).toHaveBeenCalled());
    expect(screen.getByRole("alert")).toHaveTextContent(
      "You do not have archive access for marketing content.",
    );
    expect(screen.getByRole("button", { name: "Open draft Denied Draft" })).toBeInTheDocument();
  });

  it("archives from the draft detail action using the same lifecycle path", async () => {
    vi.useRealTimers();
    vi.spyOn(window, "confirm").mockReturnValueOnce(true);
    const draft = item({ id: "content_detail_archive", status: "draft", title: "Detail Draft" });
    mockWorkspaceProfile([
      "marketing.content.view",
      "marketing.content.edit",
      "marketing.content.archive",
    ]);
    mockDrafts([draft]);
    mutationMocks.archive.mockResolvedValueOnce(item({ ...draft, status: "archived" }));

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Open draft Detail Draft" }));
    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    fireEvent.click(within(editor).getByRole("button", { name: "Archive" }));

    await waitFor(() => expect(mutationMocks.archive).toHaveBeenCalled());
    expect(screen.getByRole("status")).toHaveTextContent("Archived Detail Draft.");
    expect(
      screen.queryByRole("region", { name: "Marketing content editor" }),
    ).not.toBeInTheDocument();
  });

  it("filters draft posts with existing API dimensions and local search plus recency", () => {
    vi.mocked(campaignsLib.useCampaigns).mockReturnValue({
      data: {
        campaigns: [
          {
            ...campaign,
            members: [
              {
                display_name: "Draft Owner",
                is_owner: true,
                participation_status: "active",
                profile_id: "profile_owner",
                responsibility_label: null,
                workspace_membership_id: "membership_owner",
              },
            ],
            owner: { display_name: "Draft Owner", profile_id: "profile_owner" },
            owner_profile_id: "profile_owner",
          },
        ],
        limit: 500,
        offset: 0,
        total: 1,
      },
      error: null,
      isLoading: false,
      isMutating: false,
      reload: vi.fn(),
    });
    mockDrafts([
      item({
        id: "content_bts",
        channels: [channel({ channel: "tiktok", copy_text_override: "Alt behind clip" })],
        content_type: "video",
        copy_text: "Behind the scenes clip.",
        owner_profile_id: "profile_owner",
        status: "draft",
        title: "BTS Draft",
        updated_at: "2026-09-12T10:30:00Z",
      }),
      item({
        id: "content_radio",
        channels: [channel({ channel: "instagram" })],
        content_type: "social_post",
        copy_text: "Radio push.",
        owner_profile_id: null,
        status: "draft",
        title: "Radio Draft",
        updated_at: "2026-08-01T10:30:00Z",
      }),
    ]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));

    fireEvent.change(screen.getByLabelText("Search title or copy"), {
      target: { value: "behind" },
    });
    fireEvent.change(screen.getByLabelText("Recently updated"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Campaign"), { target: { value: "campaign_01" } });
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "tiktok" } });
    fireEvent.change(screen.getByLabelText("Content type"), { target: { value: "video" } });
    fireEvent.change(screen.getByLabelText("Artist"), { target: { value: "artist_01" } });
    fireEvent.change(screen.getByLabelText("Release"), { target: { value: "release_01" } });
    fireEvent.change(screen.getByLabelText("Owner"), { target: { value: "profile_owner" } });

    expect(screen.getByText("BTS Draft")).toBeInTheDocument();
    expect(screen.queryByText("Radio Draft")).not.toBeInTheDocument();
    expect(marketingContent.useWorkspaceMarketingContent).toHaveBeenLastCalledWith(
      "workspace_01",
      expect.objectContaining({
        artist_id: "artist_01",
        campaign_id: "campaign_01",
        channel: "tiktok",
        content_type: "video",
        limit: 500,
        offset: 0,
        owner_profile_id: "profile_owner",
        release_id: "release_01",
        status: "draft",
      }),
    );
  });

  it("clears draft filters and restores the default draft query", () => {
    mockDrafts([
      item({
        id: "content_bts",
        copy_text: "Behind the scenes clip.",
        status: "draft",
        title: "BTS Draft",
        updated_at: "2026-09-12T10:30:00Z",
      }),
      item({
        id: "content_radio",
        copy_text: "Radio push.",
        status: "draft",
        title: "Radio Draft",
        updated_at: "2026-08-01T10:30:00Z",
      }),
    ]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.change(screen.getByLabelText("Search title or copy"), {
      target: { value: "behind" },
    });

    expect(screen.getByText("BTS Draft")).toBeInTheDocument();
    expect(screen.queryByText("Radio Draft")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(screen.getByText("BTS Draft")).toBeInTheDocument();
    expect(screen.getByText("Radio Draft")).toBeInTheDocument();
    expect(screen.getByLabelText("Search title or copy")).toHaveValue("");
    expect(marketingContent.useWorkspaceMarketingContent).toHaveBeenLastCalledWith(
      "workspace_01",
      expect.objectContaining({ limit: 500, offset: 0, status: "draft" }),
    );
  });

  it("opens the drafts surface directly from navigation query params", () => {
    getParam.mockImplementation((key: string) => (key === "tab" ? "drafts" : null));
    mockDrafts([item({ id: "content_draft_01", status: "draft", title: "Draft Caption" })]);

    render(<MarketingWorkspace />);

    expect(screen.getByRole("heading", { name: "Draft Posts" })).toBeInTheDocument();
    expect(screen.getByText("Draft Caption")).toBeInTheDocument();
  });

  it("selects draft post destination accounts and surfaces account warnings", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile(["marketing.content.view", "marketing.content.create"]);
    mockSocialAccounts([
      socialConnection({
        capabilities: ["content_publish"],
        connection_method: "direct_api",
        handle: "@artist",
        id: "connection_auto",
        resolved_capabilities: {
          can_auto_publish: true,
          can_read_account_analytics: false,
          can_read_post_analytics: false,
          requires_manual_publish: false,
          supports_manual_metrics: false,
        },
      }),
      socialConnection({
        capabilities: ["manual_publish"],
        handle: "@otherartist",
        id: "connection_assisted",
      }),
      socialConnection({
        capabilities: ["account_analytics_read"],
        handle: "@readonly",
        id: "connection_readonly",
      }),
      socialConnection({
        handle: "@reconnect",
        id: "connection_reconnect",
        status: "reconnect_required",
      }),
      socialConnection({
        handle: "@offline",
        id: "connection_disconnected",
        status: "disconnected",
      }),
      socialConnection({
        handle: "@video",
        id: "connection_youtube",
        provider: "youtube",
      }),
    ]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Draft" }));

    const editor = screen.getByRole("region", { name: "Marketing content editor" });
    const destinationSelect = within(editor).getByLabelText("Destination account");
    expect(screen.getByText("Instagram - No account selected")).toBeInTheDocument();
    expect(screen.getByText("@artist - Automatic Publishing")).toBeInTheDocument();
    expect(screen.getByText("@otherartist - Assisted Publishing")).toBeInTheDocument();
    expect(screen.queryByText("@video - Assisted Publishing")).not.toBeInTheDocument();

    fireEvent.change(destinationSelect, {
      target: { value: "connection_reconnect" },
    });
    expect(screen.getByText("Reconnect required")).toBeInTheDocument();

    fireEvent.change(destinationSelect, {
      target: { value: "connection_disconnected" },
    });
    expect(screen.getByText("Disconnected")).toBeInTheDocument();

    fireEvent.change(destinationSelect, {
      target: { value: "connection_readonly" },
    });
    expect(screen.getByText("Missing publishing capability")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Account Draft" } });
    fireEvent.change(destinationSelect, {
      target: { value: "connection_auto" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() =>
      expect(mutationMocks.create).toHaveBeenCalledWith(
        expect.objectContaining({
          channels: [
            expect.objectContaining({
              channel: "instagram",
              social_account_connection_id: "connection_auto",
            }),
          ],
        }),
      ),
    );
  });

  it("keeps calendar and approval queue navigation working after visiting drafts", () => {
    mockApprovalQueue([]);

    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Drafts" }));
    expect(screen.getByRole("heading", { name: "Draft Posts" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Calendar" }));
    expect(screen.getByRole("region", { name: "Marketing content calendar" })).toBeInTheDocument();
    expect(screen.getByText("Single Teaser")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));
    expect(screen.getByRole("heading", { name: "Approval Queue" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No approvals in this queue" })).toBeInTheDocument();
  });

  it("renders the social accounts empty state and supported provider display", () => {
    mockWorkspaceProfile(["marketing.content.view", "marketing.account.view"]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));

    expect(screen.getByRole("heading", { name: "Social Account Connections" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "No social accounts registered" }),
    ).toBeInTheDocument();
    for (const provider of ["Instagram", "Facebook", "TikTok", "YouTube", "Spotify", "X"]) {
      expect(screen.getByText(provider)).toBeInTheDocument();
    }
    expect(screen.getAllByText("Direct connection not yet available").length).toBeGreaterThan(0);
    expect(socialAccounts.useSocialAccountConnections).toHaveBeenLastCalledWith("workspace_01", {
      include_disconnected: true,
      limit: 100,
      offset: 0,
    });
  });

  it("starts configured direct YouTube OAuth from social accounts", async () => {
    vi.useRealTimers();
    vi.stubEnv("NEXT_PUBLIC_YOUTUBE_DIRECT_OAUTH_ENABLED", "true");
    mockWorkspaceProfile([
      "marketing.content.view",
      "marketing.account.view",
      "marketing.account.manage",
    ]);
    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));
    expect(screen.getByText("Ready for direct connection")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Connect YouTube" }));

    await waitFor(() =>
      expect(mutationMocks.socialOAuthStart).toHaveBeenCalledWith({
        provider: "youtube",
        redirect_uri: "http://localhost:3000/api/social-account-connections/oauth/youtube/callback",
        safe_redirect_path: "/marketing?tab=accounts",
      }),
    );
    expect(mutationMocks.socialNavigate).toHaveBeenCalledWith(
      "https://accounts.google.com/o/oauth2/v2/auth?state=state_01",
    );
  });

  it("registers an assisted social account with safe metadata", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile([
      "marketing.content.view",
      "marketing.account.view",
      "marketing.account.manage",
    ]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Register Account" })[0]!);

    const form = screen.getByRole("region", { name: "Assisted account registration" });
    fireEvent.change(within(form).getByLabelText("Provider"), { target: { value: "tiktok" } });
    fireEvent.change(within(form).getByLabelText("Handle"), { target: { value: "@mira" } });
    fireEvent.change(within(form).getByLabelText("Display name"), {
      target: { value: "Mira Official" },
    });
    fireEvent.change(within(form).getByPlaceholderText("artist_profile_..."), {
      target: { value: "artist_profile_01" },
    });
    fireEvent.change(within(form).getByLabelText("Profile URL"), {
      target: { value: "https://tiktok.com/@mira" },
    });
    fireEvent.click(within(form).getByLabelText("Manual metrics entry"));
    fireEvent.change(within(form).getByLabelText("Provider metadata JSON"), {
      target: { value: '{"source":"artist-submitted"}' },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Register Assisted Account" }));

    await waitFor(() =>
      expect(mutationMocks.socialCreate).toHaveBeenCalledWith({
        artist_profile_id: "artist_profile_01",
        capabilities: ["manual_publish", "manual_metrics"],
        display_name: "Mira Official",
        handle: "@mira",
        profile_url: "https://tiktok.com/@mira",
        provider: "tiktok",
        provider_metadata: { source: "artist-submitted" },
      }),
    );
    expect(socialHookState.listReload).toHaveBeenCalled();
  });

  it("renders account cards with provider, artist, status, mode, and capabilities", () => {
    mockWorkspaceProfile(["marketing.content.view", "marketing.account.view"]);
    mockSocialAccounts([
      socialConnection({
        capabilities: ["manual_publish", "manual_metrics"],
        provider: "tiktok",
        status: "limited",
      }),
      socialConnection({
        artist_association: null,
        capabilities: ["post_analytics_read"],
        handle: "@mira-archive",
        id: "connection_02",
        provider: "x",
        status: "reconnect_required",
      }),
    ]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));

    expect(screen.getByText("@mira")).toBeInTheDocument();
    expect(screen.getAllByText("TikTok").length).toBeGreaterThan(0);
    expect(screen.getByText("Limited")).toBeInTheDocument();
    expect(screen.getAllByText("Assisted Publishing").length).toBeGreaterThan(0);
    expect(screen.getByText("Mira")).toBeInTheDocument();
    expect(
      screen.getByText("Assisted publishing checklist, Manual metrics entry"),
    ).toBeInTheDocument();
    expect(screen.getByText("@mira-archive")).toBeInTheDocument();
    expect(screen.getByText("Reconnect Required")).toBeInTheDocument();
    expect(screen.getByText("Needs reconnect")).toBeInTheDocument();
    expect(screen.getByText("Post analytics reference")).toBeInTheDocument();
  });

  it("edits social account metadata without changing connection mode", async () => {
    vi.useRealTimers();
    mockWorkspaceProfile([
      "marketing.content.view",
      "marketing.account.view",
      "marketing.account.manage",
    ]);
    mockSocialAccounts([socialConnection()]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Mira Final" } });
    fireEvent.change(screen.getByLabelText("Provider metadata JSON"), {
      target: { value: '{"notes":"verified by manager"}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(mutationMocks.socialUpdate).toHaveBeenCalledWith(
        expect.objectContaining({
          display_name: "Mira Final",
          provider_metadata: { notes: "verified by manager" },
        }),
      ),
    );
    expect(mutationMocks.socialUpdate).toHaveBeenCalledWith(
      expect.not.objectContaining({ connection_method: expect.anything() }),
    );
  });

  it("disconnects an account and keeps it visible as disconnected history", async () => {
    vi.useRealTimers();
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(true);
    mockWorkspaceProfile([
      "marketing.content.view",
      "marketing.account.view",
      "marketing.account.manage",
    ]);
    mockSocialAccounts([socialConnection()]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));

    expect(confirm).toHaveBeenCalledWith(
      "Disconnect Instagram @mira? It will remain visible in social account history.",
    );
    await waitFor(() => expect(mutationMocks.socialDisconnect).toHaveBeenCalled());
    expect(screen.getByText("@mira")).toBeInTheDocument();
    expect(screen.getAllByText("Disconnected").length).toBeGreaterThan(0);
    expect(socialHookState.listReload).toHaveBeenCalled();
  });

  it("shows account view while hiding manage UI without manage access", () => {
    mockWorkspaceProfile(["marketing.content.view", "marketing.account.view"]);
    mockSocialAccounts([socialConnection()]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));

    expect(screen.getByText("@mira")).toBeInTheDocument();
    expect(
      screen.getByText(/need marketing account manage access to register, edit, or disconnect/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Register Account" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disconnect" })).not.toBeInTheDocument();
  });

  it("blocks unauthorized social account view access", () => {
    mockWorkspaceProfile(["marketing.content.view"]);

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));

    expect(screen.getByRole("status")).toHaveTextContent(
      "You need marketing account view access to open Social Account Connections.",
    );
    expect(
      screen.queryByRole("heading", { name: "Social Account Connections" }),
    ).not.toBeInTheDocument();
  });

  it("shows social account API errors", () => {
    mockWorkspaceProfile(["marketing.content.view", "marketing.account.view"]);
    mockSocialAccountsError(
      new socialAccounts.SocialAccountConnectionApiError(
        "network_failure",
        "Unable to reach the social account connections API.",
      ),
    );

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Social account connections could not be loaded.",
    );
  });

  it("shows the social accounts loading state", () => {
    mockWorkspaceProfile(["marketing.content.view", "marketing.account.view"]);
    mockSocialAccountsLoading();

    render(<MarketingWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));

    expect(screen.getByText("Loading social account connections")).toBeInTheDocument();
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
    expect(
      marketingContent.shouldInvalidateMarketingContentRealtimeCacheKey({
        campaignId: "campaign_01",
        contentItemId: "content_01",
        key: "marketing-content:workspace-list:workspace_01:limit:500|offset:0|status:draft",
        workspaceId: "workspace_01",
      }),
    ).toBe(true);
  });
});
