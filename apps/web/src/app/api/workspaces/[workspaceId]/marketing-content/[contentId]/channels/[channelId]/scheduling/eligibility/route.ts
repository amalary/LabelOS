import { proxyWorkspaceRequest } from "../../../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(
  request: Request,
  context: { params: Promise<{ workspaceId: string; contentId: string; channelId: string }> },
) {
  const { workspaceId, contentId, channelId } = await context.params;
  return proxyWorkspaceRequest(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/marketing-content/${encodeURIComponent(contentId)}/channels/${encodeURIComponent(channelId)}/scheduling/eligibility`,
    { headers: { Accept: "application/json" } },
  );
}
