import { proxyWorkspaceRequest } from "../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(_request: Request, context: { params: Promise<{ workspaceId: string }> }) {
  return context.params.then(({ workspaceId }) =>
    proxyWorkspaceRequest(`/api/v1/workspaces/${workspaceId}/campaigns`, {
      headers: {
        Accept: "application/json",
      },
    }),
  );
}
