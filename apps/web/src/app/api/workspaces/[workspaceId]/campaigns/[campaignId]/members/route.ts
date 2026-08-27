import { proxyWorkspaceRequest } from "../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; campaignId: string }> },
) {
  return context.params.then(({ workspaceId, campaignId }) =>
    proxyWorkspaceRequest(`/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/members`, {
      headers: {
        Accept: "application/json",
      },
    }),
  );
}

export async function PUT(
  request: Request,
  context: { params: Promise<{ workspaceId: string; campaignId: string }> },
) {
  const { workspaceId, campaignId } = await context.params;
  return proxyWorkspaceRequest(
    `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/members`,
    {
      method: "PUT",
      body: await request.text(),
      headers: {
        Accept: "application/json",
        "Content-Type": request.headers.get("content-type") ?? "application/json",
      },
    },
  );
}
