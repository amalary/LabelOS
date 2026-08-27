import { proxyWorkspaceRequest } from "../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function PATCH(
  request: Request,
  context: { params: Promise<{ workspaceId: string; campaignId: string; milestoneId: string }> },
) {
  const { workspaceId, campaignId, milestoneId } = await context.params;
  return proxyWorkspaceRequest(
    `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/milestones/${milestoneId}`,
    {
      method: "PATCH",
      body: await request.text(),
      headers: {
        Accept: "application/json",
        "Content-Type": request.headers.get("content-type") ?? "application/json",
      },
    },
  );
}

export function DELETE(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; campaignId: string; milestoneId: string }> },
) {
  return context.params.then(({ workspaceId, campaignId, milestoneId }) =>
    proxyWorkspaceRequest(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/milestones/${milestoneId}`,
      {
        method: "DELETE",
      },
    ),
  );
}
