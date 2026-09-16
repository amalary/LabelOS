import { proxyWorkspaceRequest } from "../../../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(
  request: Request,
  context: { params: Promise<{ workspaceId: string; contentId: string; channelId: string }> },
) {
  const { workspaceId, contentId, channelId } = await context.params;
  return proxyWorkspaceRequest(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/marketing-content/${encodeURIComponent(contentId)}/channels/${encodeURIComponent(channelId)}/scheduling/activate`,
    {
      method: "POST",
      body: await request.text(),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": request.headers.get("Idempotency-Key") ?? "",
      },
    },
  );
}
