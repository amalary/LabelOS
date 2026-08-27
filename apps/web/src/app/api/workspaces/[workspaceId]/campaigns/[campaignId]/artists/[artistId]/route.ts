import { proxyWorkspaceRequest } from "../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function DELETE(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; campaignId: string; artistId: string }> },
) {
  return context.params.then(({ workspaceId, campaignId, artistId }) =>
    proxyWorkspaceRequest(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/artists/${artistId}`,
      {
        method: "DELETE",
      },
    ),
  );
}
