import { beforeEach, describe, expect, it, vi } from "vitest";

import { GET as listApprovals } from "./[workspaceId]/approvals/route";
import { GET as getApproval } from "./[workspaceId]/approvals/[approvalRequestId]/route";
import {
  GET as getDecisions,
  POST as postDecision,
} from "./[workspaceId]/approvals/[approvalRequestId]/decisions/route";
import { POST as assignReviewer } from "./[workspaceId]/approvals/[approvalRequestId]/assign/route";
import { POST as submitMarketingContentApproval } from "./[workspaceId]/campaigns/[campaignId]/marketing-content/[contentId]/approval-requests/route";
import { apiFetch } from "../../../lib/api-client";

vi.mock("../../../lib/api-client", () => ({
  ApiClientError: class ApiClientError extends Error {
    code = "network_failure";
    status = 502;
  },
  apiFetch: vi.fn(),
}));

const workspaceContext = { params: Promise.resolve({ workspaceId: "workspace_01" }) };
const approvalContext = {
  params: Promise.resolve({ workspaceId: "workspace_01", approvalRequestId: "approval_01" }),
};
const marketingContentContext = {
  params: Promise.resolve({
    workspaceId: "workspace_01",
    campaignId: "campaign_01",
    contentId: "content_01",
  }),
};

describe("approval proxy routes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiFetch).mockResolvedValue(Response.json({ ok: true }));
  });

  it("constructs approval list URLs with query filters", async () => {
    await listApprovals(
      new Request("http://localhost/api/workspaces/workspace_01/approvals?status=in_review&limit=25"),
      workspaceContext,
    );

    expect(apiFetch).toHaveBeenCalledWith(
      "/api/v1/workspaces/workspace_01/approvals?status=in_review&limit=25",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("constructs approval detail and decision history URLs", async () => {
    await getApproval(new Request("http://localhost"), approvalContext);
    await getDecisions(new Request("http://localhost"), approvalContext);

    expect(apiFetch).toHaveBeenNthCalledWith(
      1,
      "/api/v1/workspaces/workspace_01/approvals/approval_01",
      expect.any(Object),
    );
    expect(apiFetch).toHaveBeenNthCalledWith(
      2,
      "/api/v1/workspaces/workspace_01/approvals/approval_01",
      expect.any(Object),
    );
  });

  it("constructs mutation URLs and forwards request bodies", async () => {
    await postDecision(
      new Request("http://localhost", {
        method: "POST",
        body: JSON.stringify({ action: "approved" }),
        headers: { "Content-Type": "application/json" },
      }),
      approvalContext,
    );
    await assignReviewer(
      new Request("http://localhost", {
        method: "POST",
        body: JSON.stringify({ assigned_profile_id: "profile_02" }),
      }),
      approvalContext,
    );
    await submitMarketingContentApproval(
      new Request("http://localhost", {
        method: "POST",
        body: JSON.stringify({ summary: "Ready" }),
      }),
      marketingContentContext,
    );

    expect(apiFetch).toHaveBeenNthCalledWith(
      1,
      "/api/v1/workspaces/workspace_01/approvals/approval_01/decisions",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "approved" }) }),
    );
    expect(apiFetch).toHaveBeenNthCalledWith(
      2,
      "/api/v1/workspaces/workspace_01/approvals/approval_01/assign",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ assigned_profile_id: "profile_02" }),
      }),
    );
    expect(apiFetch).toHaveBeenNthCalledWith(
      3,
      "/api/v1/workspaces/workspace_01/campaigns/campaign_01/marketing-content/content_01/approval-requests",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ summary: "Ready" }) }),
    );
  });
});
