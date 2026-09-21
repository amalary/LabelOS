import { proxyPublicationRead } from "../../../publications-proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; publicationId: string }> },
) {
  const { workspaceId, publicationId } = await context.params;
  return proxyPublicationRead(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/publications/${encodeURIComponent(publicationId)}`,
  );
}
