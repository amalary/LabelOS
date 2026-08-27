import { proxyWorkspaceRequest } from "../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function DELETE(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; campaignId: string; releaseId: string }> },
) {
  return context.params.then(({ workspaceId, campaignId, releaseId }) =>
    proxyWorkspaceRequest(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/releases/${releaseId}`,
      {
        method: "DELETE",
      },
    ),
  );
}
