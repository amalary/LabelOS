import { proxyProfileRequest } from "../../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; profileId: string }> },
) {
  return context.params.then(({ profileId, workspaceId }) =>
    proxyProfileRequest(`/api/v1/workspaces/${workspaceId}/profiles/${profileId}`, {
      headers: {
        Accept: "application/json",
      },
    }),
  );
}
