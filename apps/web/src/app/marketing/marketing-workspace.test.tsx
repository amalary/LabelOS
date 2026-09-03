import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MarketingWorkspace } from "./marketing-workspace";
import type { MarketingContentItem } from "../../lib/marketing-content";

vi.mock("../../lib/workspace-context", () => ({
  useActiveWorkspace: vi.fn(),
  useActiveWorkspaceProfile: vi.fn(),
}));

vi.mock("../../lib/marketing-content", async () => {
  const actual =
    await vi.importActual<typeof import("../../lib/marketing-content")>(
      "../../lib/marketing-content",
    );
  return {
    ...actual,
    useWorkspaceCalendarContent: vi.fn(),
  };
});

const workspaceContext = await import("../../lib/workspace-context");
const marketingContent = await import("../../lib/marketing-content");

const contentItem: MarketingContentItem = {
  id: "content_01",
  workspace_id: "workspace_01",
  campaign_id: "campaign_01",
  title: "Announcement post",
  content_type: "social_post",
  copy_text: "Out Friday",
  asset_refs: [],
  metadata: {},
  status: "scheduled",
  artist_id: null,
  release_id: null,
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
};

function mockWorkspaceProfile(capabilities: string[] = ["marketing.content.view"]) {
  vi.mocked(workspaceContext.useActiveWorkspace).mockReturnValue({
    activeWorkspace: {
      id: "workspace_01",
      name: "Alpha Label",
      slug: "alpha",
      role: "member",
      workspace_permission: "member",
      department_access: ["marketing"],
      capability_permissions: capabilities,
      can_switch: true,
    },
    hasActiveWorkspace: true,
    workspaces: [],
  });
  vi.mocked(workspaceContext.useActiveWorkspaceProfile).mockReturnValue({
    capabilities,
    canEditProfile: false,
    departmentAccess: ["marketing"],
    isLoading: false,
    membership: null,
    responsibilities: [],
    roles: ["member"],
    subject: {
      role: "member",
      workspacePermission: "member",
      departmentAccess: ["marketing"],
      capabilities,
    },
  });
}

describe("MarketingWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockWorkspaceProfile();
    vi.mocked(marketingContent.useWorkspaceCalendarContent).mockReturnValue({
      data: {
        marketing_content: [contentItem],
        total: 1,
        limit: 100,
        offset: 0,
      },
      error: null,
      isLoading: false,
      isMutating: false,
      reload: vi.fn(),
    });
  });

  it("renders the Marketing Hub calendar entry with real content rows", () => {
    render(<MarketingWorkspace />);

    expect(screen.getByRole("heading", { name: "Marketing" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Marketing Hub sections" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Calendar" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByText("Announcement post")).toBeInTheDocument();
    expect(screen.getByText("Social Post - instagram / feed")).toBeInTheDocument();
  });

  it("keeps upcoming tabs as lightweight placeholders", () => {
    render(<MarketingWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Drafts Upcoming" }));

    expect(screen.getByRole("heading", { name: "Drafts upcoming" })).toBeInTheDocument();
    expect(screen.queryByText("Announcement post")).not.toBeInTheDocument();
  });

  it("renders permission denied without showing calendar content", () => {
    mockWorkspaceProfile([]);

    render(<MarketingWorkspace />);

    expect(screen.getByText("You need marketing content view access to open the Marketing Hub.")).toBeInTheDocument();
    expect(screen.queryByText("Announcement post")).not.toBeInTheDocument();
  });

  it("renders loading, api-error, and empty calendar states", () => {
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
      data: {
        marketing_content: [],
        total: 0,
        limit: 100,
        offset: 0,
      },
      error: null,
      isLoading: false,
      isMutating: false,
      reload: vi.fn(),
    });
    rerender(<MarketingWorkspace />);
    expect(screen.getByRole("heading", { name: "No scheduled content" })).toBeInTheDocument();
  });
});
