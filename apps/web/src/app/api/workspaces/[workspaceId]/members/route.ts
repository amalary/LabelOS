import { proxyWorkspaceRequest } from "../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(
  request: Request,
  context: { params: Promise<{ workspaceId: string }> },
) {
  return context.params.then(({ workspaceId }) => {
    const url = new URL(request.url);
    return proxyWorkspaceRequest(
      `/api/v1/organizations/${workspaceId}/members${url.search}`,
      {
        headers: {
          Accept: "application/json",
        },
      },
    );
  });
}
