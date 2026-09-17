import { proxyWorkspaceRequest } from "../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request, context: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await context.params;
  return proxyWorkspaceRequest(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/scheduling/jobs${new URL(request.url).search}`,
    { headers: { Accept: "application/json" } },
  );
}
