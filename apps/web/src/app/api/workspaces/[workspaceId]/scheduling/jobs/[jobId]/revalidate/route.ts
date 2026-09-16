import { proxyWorkspaceRequest } from "../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(
  request: Request,
  context: { params: Promise<{ workspaceId: string; jobId: string }> },
) {
  const { workspaceId, jobId } = await context.params;
  return proxyWorkspaceRequest(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/scheduling/jobs/${encodeURIComponent(jobId)}/revalidate`,
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
