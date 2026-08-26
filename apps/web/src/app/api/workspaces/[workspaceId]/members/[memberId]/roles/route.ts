import { proxyWorkspaceRequest } from "../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function PUT(
  request: Request,
  context: { params: Promise<{ workspaceId: string; memberId: string }> },
) {
  return context.params.then(({ memberId, workspaceId }) =>
    request.text().then((body) =>
      proxyWorkspaceRequest(
        `/api/v1/organizations/${workspaceId}/members/${memberId}/roles`,
        {
          body,
          headers: {
            Accept: "application/json",
            "Content-Type": request.headers.get("content-type") ?? "application/json",
          },
          method: "PUT",
        },
      ),
    ),
  );
}
