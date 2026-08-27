import { proxyWorkspaceRequest } from "../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; campaignId: string }> },
) {
  return context.params.then(({ workspaceId, campaignId }) =>
    proxyWorkspaceRequest(`/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}`, {
      headers: {
        Accept: "application/json",
      },
    }),
  );
}
