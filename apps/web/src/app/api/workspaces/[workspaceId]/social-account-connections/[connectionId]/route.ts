import { proxyWorkspaceRequest } from "../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; connectionId: string }> },
) {
  return context.params.then(({ workspaceId, connectionId }) =>
    proxyWorkspaceRequest(
      `/api/v1/workspaces/${workspaceId}/social-account-connections/${connectionId}`,
      {
        headers: {
          Accept: "application/json",
        },
      },
    ),
  );
}

export async function PATCH(
  request: Request,
  context: { params: Promise<{ workspaceId: string; connectionId: string }> },
) {
  const { workspaceId, connectionId } = await context.params;
  return proxyWorkspaceRequest(
    `/api/v1/workspaces/${workspaceId}/social-account-connections/${connectionId}`,
    {
      method: "PATCH",
      body: await request.text(),
      headers: {
        Accept: "application/json",
        "Content-Type": request.headers.get("content-type") ?? "application/json",
      },
    },
  );
}
