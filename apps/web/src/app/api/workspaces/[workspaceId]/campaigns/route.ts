import { proxyWorkspaceRequest } from "../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: Request, context: { params: Promise<{ workspaceId: string }> }) {
  const query = new URL(request.url).search;
  return context.params.then(({ workspaceId }) =>
    proxyWorkspaceRequest(`/api/v1/workspaces/${workspaceId}/campaigns${query}`, {
      headers: {
        Accept: "application/json",
      },
    }),
  );
}

export async function POST(
  request: Request,
  context: { params: Promise<{ workspaceId: string }> },
) {
  const { workspaceId } = await context.params;
  return proxyWorkspaceRequest(`/api/v1/workspaces/${workspaceId}/campaigns`, {
    method: "POST",
    body: await request.text(),
    headers: {
      Accept: "application/json",
      "Content-Type": request.headers.get("content-type") ?? "application/json",
    },
  });
}
