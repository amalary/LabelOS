import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApprovalApiError,
  approvalQueryKeys,
  approveApprovalRequest,
  assignApprovalReviewer,
  clearApprovalCache,
  getApprovalRequest,
  handleApprovalRealtimeInvalidation,
  listApprovalDecisionHistory,
  listApprovals,
  rejectApprovalRequest,
  requestApprovalChanges,
  shouldInvalidateApprovalRealtimeCacheKey,
  submitMarketingContentForApproval,
  useApprovalQueue,
  useSubmitMarketingContentForApproval,
} from "./approvals";
import { clearMarketingContentCache, useMarketingContentItem } from "./marketing-content";

const approvalSummary = {
  id: "approval_01",
  workspace_id: "workspace_01",
  resource_type: "marketing_content_item",
  resource_id: "content_01",
  submitted_revision: 3,
  status: "in_review",
  current_stage: null,
  stage_assignment: null,
  submitter: {
    user_id: "user_01",
    profile_id: "profile_01",
    actor_kind: "user",
    actor_key: "user_01",
    display_name: "Mara Chen",
  },
  title: "Announcement post",
  summary: null,
  submitted_at: "2026-09-01T12:00:00Z",
  resolved_at: null,
  campaign: { id: "campaign_01", name: "Single Launch" },
  artist: null,
} as const;

const approvalDetail = {
  ...approvalSummary,
  current_resource_revision: 3,
  is_stale: false,
  decision_history: [
    {
      id: "decision_01",
      stage_id: null,
      decision: "submitted",
      decided_by_user_id: "user_01",
      decided_by_profile_id: "profile_01",
      actor_kind: "user",
      actor_key: "user_01",
      reason: null,
      payload: {},
      created_at: "2026-09-01T12:00:00Z",
    },
  ],
  marketing_content_preview: {
    id: "content_01",
    title: "Announcement post",
    content_type: "social_post",
    copy_text: "Out Friday",
    asset_refs: [],
    status: "in_review",
    current_revision: 3,
    approved_revision: null,
  },
  release: null,
  channels: [],
  available_actions: ["approved", "rejected", "changes_requested", "cancelled"],
} as const;

const marketingContentItem = {
  id: "content_01",
  workspace_id: "workspace_01",
  campaign_id: "campaign_01",
  title: "Announcement post",
  content_type: "social_post",
  copy_text: "Out Friday",
  asset_refs: [],
  metadata: {},
  status: "in_review",
  artist_id: null,
  release_id: null,
  owner_profile_id: null,
  created_by_user_id: "user_01",
  created_by_profile_id: "profile_01",
  scheduled_at: null,
  published_at: null,
  approval_requested_at: "2026-09-01T12:00:00Z",
  approved_at: null,
  approved_by_profile_id: null,
  channels: [],
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
} as const;

function ApprovalQueueProbe() {
  const approvals = useApprovalQueue("workspace_01", { status: "in_review", limit: 25 });
  return <span>{approvals.data?.total ?? "loading"}</span>;
}

function MarketingContentProbe() {
  const item = useMarketingContentItem("workspace_01", "campaign_01", "content_01");
  return <span>{item.data?.title ?? "loading"}</span>;
}

function PendingSubmitProbe() {
  const mutation = useSubmitMarketingContentForApproval(
    "workspace_01",
    "campaign_01",
    "content_01",
  );
  return (
    <button
      onClick={() => {
        void mutation.mutate({ summary: "Ready" }).catch(() => undefined);
        void mutation.mutate({ summary: "Again" }).catch((error: unknown) => {
          if (error instanceof ApprovalApiError) {
            document.body.dataset.pendingError = error.code;
          }
        });
      }}
    >
      {mutation.isMutating ? "pending" : "submit"}
    </button>
  );
}

describe("approvals data layer", () => {
  beforeEach(() => {
    clearApprovalCache();
    clearMarketingContentCache();
    document.body.dataset.pendingError = "";
    vi.stubGlobal("fetch", vi.fn());
  });

  it("lists approval requests through the workspace proxy with queue filters", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ approvals: [approvalSummary], total: 1, limit: 25, offset: 50 }),
    );

    await expect(
      listApprovals("workspace_01", {
        status: "in_review",
        resource_type: "marketing_content_item",
        campaign_id: "campaign_01",
        artist_id: "artist_01",
        submitter_user_id: "user_01",
        submitter_profile_id: "profile_01",
        assigned_reviewer_profile_id: "profile_02",
        assigned_to_me: true,
        submitted_by_me: false,
        submitted_start: "2026-09-01T00:00:00Z",
        submitted_end: "2026-09-30T23:59:59Z",
        limit: 25,
        offset: 50,
      }),
    ).resolves.toMatchObject({ total: 1 });

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/approvals?status=in_review&resource_type=marketing_content_item&campaign_id=campaign_01&artist_id=artist_01&submitter_user_id=user_01&submitter_profile_id=profile_01&assigned_reviewer_profile_id=profile_02&assigned_to_me=true&submitted_by_me=false&submitted_start=2026-09-01T00%3A00%3A00Z&submitted_end=2026-09-30T23%3A59%3A59Z&limit=25&offset=50",
      expect.objectContaining({ cache: "no-store", headers: expect.any(Headers) }),
    );
  });

  it("uses explicit stable workspace cache keys", () => {
    expect(
      approvalQueryKeys.workspaceList("workspace_01", {
        limit: 25,
        offset: 0,
        status: "requested",
      }),
    ).toBe("approvals:workspace-list:workspace_01:limit:25|offset:0|status:requested");
    expect(approvalQueryKeys.detail("workspace_01", "approval_01")).toBe(
      "approvals:detail:workspace_01:approval_01",
    );
    expect(approvalQueryKeys.decisions("workspace_01", "approval_01")).toBe(
      "approvals:decisions:workspace_01:approval_01",
    );
  });

  it("reads details, available actions, decision history, assignment, and decisions", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json({ ...approvalDetail, channels: undefined }))
      .mockResolvedValueOnce(Response.json(approvalDetail))
      .mockResolvedValueOnce(Response.json({ ...approvalDetail, stage_assignment: { profile_id: "profile_02" } }))
      .mockResolvedValueOnce(Response.json({ ...approvalDetail, status: "approved" }))
      .mockResolvedValueOnce(Response.json({ ...approvalDetail, status: "rejected" }))
      .mockResolvedValueOnce(Response.json({ ...approvalDetail, status: "changes_requested" }));

    await expect(getApprovalRequest("workspace_01", "approval_01")).resolves.toMatchObject({
      available_actions: ["approved", "rejected", "changes_requested", "cancelled"],
      channels: [],
    });
    await expect(listApprovalDecisionHistory("workspace_01", "approval_01")).resolves.toHaveLength(1);
    await expect(
      assignApprovalReviewer("workspace_01", "approval_01", { assigned_profile_id: "profile_02" }),
    ).resolves.toMatchObject({ stage_assignment: { profile_id: "profile_02" } });
    await expect(approveApprovalRequest("workspace_01", "approval_01")).resolves.toMatchObject({
      status: "approved",
    });
    await expect(
      rejectApprovalRequest("workspace_01", "approval_01", { reason: "Needs revision" }),
    ).resolves.toMatchObject({ status: "rejected" });
    await expect(
      requestApprovalChanges("workspace_01", "approval_01", { reason: "Tighten copy" }),
    ).resolves.toMatchObject({ status: "changes_requested" });

    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/workspaces/workspace_01/approvals/approval_01/decisions",
      expect.any(Object),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      "/api/workspaces/workspace_01/approvals/approval_01/assign",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      4,
      "/api/workspaces/workspace_01/approvals/approval_01/decisions",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("submits marketing content for approval and propagates workspace ids", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(approvalDetail, { status: 201 }));

    await expect(
      submitMarketingContentForApproval("workspace_01", "campaign_01", "content_01", {
        summary: "Ready",
        metadata: { source: "calendar" },
      }),
    ).resolves.toMatchObject({ id: "approval_01" });

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/campaigns/campaign_01/marketing-content/content_01/approval-requests",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("invalidates approval list and targeted marketing content caches after approval mutations", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json({ approvals: [approvalSummary], total: 1, limit: 25, offset: 0 }))
      .mockResolvedValueOnce(Response.json(marketingContentItem))
      .mockResolvedValueOnce(Response.json(approvalDetail))
      .mockResolvedValueOnce(Response.json({ approvals: [approvalSummary], total: 1, limit: 25, offset: 0 }))
      .mockResolvedValueOnce(Response.json(marketingContentItem));

    render(
      <>
        <ApprovalQueueProbe />
        <MarketingContentProbe />
      </>,
    );

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await approveApprovalRequest("workspace_01", "approval_01");
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(5));

    expect(fetch).toHaveBeenNthCalledWith(
      4,
      "/api/workspaces/workspace_01/approvals?status=in_review&limit=25",
      expect.any(Object),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      5,
      "/api/workspaces/workspace_01/campaigns/campaign_01/marketing-content/content_01",
      expect.any(Object),
    );
  });

  it("invalidates approval and marketing content caches for approval.updated realtime events", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json({ approvals: [approvalSummary], total: 1, limit: 25, offset: 0 }))
      .mockResolvedValueOnce(Response.json(marketingContentItem))
      .mockResolvedValueOnce(Response.json({ approvals: [approvalSummary], total: 1, limit: 25, offset: 0 }))
      .mockResolvedValueOnce(Response.json(marketingContentItem));

    render(
      <>
        <ApprovalQueueProbe />
        <MarketingContentProbe />
      </>,
    );

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    handleApprovalRealtimeInvalidation({
      approvalRequestId: "approval_01",
      campaignId: "campaign_01",
      contentItemId: "content_01",
      workspaceId: "workspace_01",
    });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4));
  });

  it("matches approval realtime cache keys by workspace and request id", () => {
    const shouldInvalidate = (key: string) =>
      shouldInvalidateApprovalRealtimeCacheKey({
        approvalRequestId: "approval_01",
        key,
        workspaceId: "workspace_01",
      });

    expect(shouldInvalidate("approvals:workspace-list:workspace_01:default")).toBe(true);
    expect(shouldInvalidate("approvals:detail:workspace_01:approval_01")).toBe(true);
    expect(shouldInvalidate("approvals:decisions:workspace_01:approval_01")).toBe(true);
    expect(shouldInvalidate("approvals:workspace-list:workspace_02:default")).toBe(false);
    expect(shouldInvalidate("approvals:detail:workspace_01:approval_02")).toBe(false);
  });

  it("normalizes conflict and stale revision errors", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json({ detail: "Already resolved" }, { status: 409 }))
      .mockResolvedValueOnce(
        Response.json({ detail: "Approval stale resource revision" }, { status: 409 }),
      );

    await expect(approveApprovalRequest("workspace_01", "approval_01")).rejects.toMatchObject({
      code: "conflict",
      status: 409,
    });
    await expect(approveApprovalRequest("workspace_01", "approval_01")).rejects.toMatchObject({
      code: "stale_revision",
      status: 409,
    });
  });

  it("prevents repeated submissions while a mutation is pending", async () => {
    let resolveRequest: (value: Response) => void = () => undefined;
    vi.mocked(fetch).mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveRequest = resolve;
      }),
    );

    render(<PendingSubmitProbe />);
    act(() => {
      screen.getByRole("button").click();
    });

    await waitFor(() => expect(document.body.dataset.pendingError).toBe("conflict"));
    expect(fetch).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveRequest(Response.json(approvalDetail));
    });
  });
});
