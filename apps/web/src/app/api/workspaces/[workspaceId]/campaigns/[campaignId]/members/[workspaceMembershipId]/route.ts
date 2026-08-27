import { proxyWorkspaceRequest } from "../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function DELETE(
  _request: Request,
  context: {
    params: Promise<{
      workspaceId: string;
      campaignId: string;
      workspaceMembershipId: string;
    }>;
  },
) {
  return context.params.then(({ workspaceId, campaignId, workspaceMembershipId }) =>
    proxyWorkspaceRequest(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/members/${workspaceMembershipId}`,
      {
        method: "DELETE",
      },
    ),
  );
}
