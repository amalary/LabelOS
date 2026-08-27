import { proxyWorkspaceRequest } from "../../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function POST(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; campaignId: string; milestoneId: string }> },
) {
  return context.params.then(({ workspaceId, campaignId, milestoneId }) =>
    proxyWorkspaceRequest(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/milestones/${milestoneId}/complete`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
        },
      },
    ),
  );
}
