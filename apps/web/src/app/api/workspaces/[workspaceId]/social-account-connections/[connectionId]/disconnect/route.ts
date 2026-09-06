import { proxyWorkspaceRequest } from "../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function POST(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; connectionId: string }> },
) {
  return context.params.then(({ workspaceId, connectionId }) =>
    proxyWorkspaceRequest(
      `/api/v1/workspaces/${workspaceId}/social-account-connections/${connectionId}/disconnect`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
        },
      },
    ),
  );
}
