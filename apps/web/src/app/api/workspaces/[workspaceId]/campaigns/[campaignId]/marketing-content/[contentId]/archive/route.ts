import { proxyWorkspaceRequest } from "../../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; campaignId: string; contentId: string }> },
) {
  const { workspaceId, campaignId, contentId } = await context.params;
  return proxyWorkspaceRequest(
    `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/marketing-content/${contentId}/archive`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
    },
  );
}
