import { proxyWorkspaceRequest } from "../../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(
  request: Request,
  context: { params: Promise<{ workspaceId: string; campaignId: string; contentId: string }> },
) {
  const { workspaceId, campaignId, contentId } = await context.params;
  return proxyWorkspaceRequest(
    `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/marketing-content/${contentId}/approval-requests`,
    {
      method: "POST",
      body: await request.text(),
      headers: {
        Accept: "application/json",
        "Content-Type": request.headers.get("content-type") ?? "application/json",
      },
    },
  );
}
