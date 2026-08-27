import { proxyWorkspaceRequest } from "../../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function POST(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; campaignId: string; goalId: string }> },
) {
  return context.params.then(({ workspaceId, campaignId, goalId }) =>
    proxyWorkspaceRequest(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/goals/${goalId}/archive`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
        },
      },
    ),
  );
}
