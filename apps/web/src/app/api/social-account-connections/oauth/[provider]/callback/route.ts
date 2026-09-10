import { proxyWorkspaceRequest } from "../../../../workspaces/proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(
  request: Request,
  context: { params: Promise<{ provider: string }> },
) {
  const url = new URL(request.url);
  const query = new URLSearchParams(url.search);
  query.set("redirect_uri", `${url.origin}${url.pathname}`);
  return context.params.then(({ provider }) =>
    proxyWorkspaceRequest(
      `/api/v1/social-account-connections/oauth/${provider}/callback?${query.toString()}`,
      {
        headers: {
          Accept: "application/json",
        },
        redirect: "manual",
      },
    ),
  );
}
