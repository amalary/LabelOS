import { proxyWorkspaceRequest } from "../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: Request, context: { params: Promise<{ workspaceId: string }> }) {
  const query = new URL(request.url).search;
  return context.params.then(({ workspaceId }) =>
    proxyWorkspaceRequest(`/api/v1/workspaces/${workspaceId}/analytics/series${query}`, {
      headers: {
        Accept: "application/json",
      },
    }),
  );
}
