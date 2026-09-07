import { proxyWorkspaceRequest } from "../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(
  request: Request,
  context: { params: Promise<{ workspaceId: string; provider: string }> },
) {
  const query = new URL(request.url).search;
  return context.params.then(({ workspaceId, provider }) =>
    proxyWorkspaceRequest(
      `/api/v1/workspaces/${workspaceId}/social-account-connections/oauth/${provider}/callback${query}`,
      {
        headers: {
          Accept: "application/json",
        },
        redirect: "manual",
      },
    ),
  );
}
