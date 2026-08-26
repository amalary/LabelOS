import { proxyProfileRequest } from "../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(
  _request: Request,
  context: { params: Promise<{ artistProfileId: string; workspaceId: string }> },
) {
  return context.params.then(({ artistProfileId, workspaceId }) =>
    proxyProfileRequest(`/api/v1/workspaces/${workspaceId}/artist-profiles/${artistProfileId}`, {
      headers: {
        Accept: "application/json",
      },
    }),
  );
}

export async function PATCH(
  request: Request,
  context: { params: Promise<{ artistProfileId: string; workspaceId: string }> },
) {
  const body = await request.text();
  return context.params.then(({ artistProfileId, workspaceId }) =>
    proxyProfileRequest(`/api/v1/workspaces/${workspaceId}/artist-profiles/${artistProfileId}`, {
      body,
      headers: {
        Accept: "application/json",
        "Content-Type": request.headers.get("content-type") ?? "application/json",
      },
      method: "PATCH",
    }),
  );
}
