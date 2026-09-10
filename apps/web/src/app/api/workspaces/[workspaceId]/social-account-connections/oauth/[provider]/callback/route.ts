import { proxyWorkspaceRequest } from "../../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(
  request: Request,
  context: { params: Promise<{ workspaceId: string; provider: string }> },
) {
  const url = new URL(request.url);
  const query = new URLSearchParams(url.search);
  query.set("redirect_uri", `${url.origin}${url.pathname}`);
  return context.params.then(({ workspaceId, provider }) =>
    proxyWorkspaceRequest(
      `/api/v1/workspaces/${workspaceId}/social-account-connections/oauth/${provider}/callback?${query.toString()}`,
      {
        headers: {
          Accept: "application/json",
        },
        redirect: "manual",
      },
    ),
  );
}
