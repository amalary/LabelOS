import { proxyProfileRequest } from "../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(
  request: Request,
  context: { params: Promise<{ workspaceId: string }> },
) {
  const body = await request.text();
  return context.params.then(({ workspaceId }) =>
    proxyProfileRequest(`/api/v1/workspaces/${workspaceId}/artist-profiles`, {
      body,
      headers: {
        Accept: "application/json",
        "Content-Type": request.headers.get("content-type") ?? "application/json",
      },
      method: "POST",
    }),
  );
}
