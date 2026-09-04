import { proxyWorkspaceRequest } from "../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; approvalRequestId: string }> },
) {
  return context.params.then(({ workspaceId, approvalRequestId }) =>
    proxyWorkspaceRequest(`/api/v1/workspaces/${workspaceId}/approvals/${approvalRequestId}`, {
      headers: {
        Accept: "application/json",
      },
    }),
  );
}
