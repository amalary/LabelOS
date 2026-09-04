import { proxyWorkspaceRequest } from "../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(
  request: Request,
  context: { params: Promise<{ workspaceId: string; approvalRequestId: string }> },
) {
  const { workspaceId, approvalRequestId } = await context.params;
  return proxyWorkspaceRequest(
    `/api/v1/workspaces/${workspaceId}/approvals/${approvalRequestId}/assign`,
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
