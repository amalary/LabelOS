import { proxyWorkspaceRequest } from "../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(
  request: Request,
  context: { params: Promise<{ workspaceId: string; jobId: string }> },
) {
  const { workspaceId, jobId } = await context.params;
  return proxyWorkspaceRequest(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/scheduling/jobs/${encodeURIComponent(jobId)}/blocked-reasons`,
    { headers: { Accept: "application/json" } },
  );
}
