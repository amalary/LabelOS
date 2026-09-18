import { proxyPublicationCommand } from "../../../../../publications-proxy";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export async function POST(
  request: Request,
  context: { params: Promise<{ workspaceId: string; publicationId: string }> },
) {
  const { workspaceId, publicationId } = await context.params;
  return proxyPublicationCommand(
    request,
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/publications/${encodeURIComponent(publicationId)}/manual/start`,
  );
}
