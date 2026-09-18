import { proxyPublicationAsset } from "../../../../../publications-proxy";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export async function GET(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; publicationId: string; sha256: string }> },
) {
  const { workspaceId, publicationId, sha256 } = await context.params;
  if (!/^[a-f0-9]{64}$/.test(sha256))
    return Response.json({ detail: "Invalid asset" }, { status: 400 });
  return proxyPublicationAsset(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/publications/${encodeURIComponent(publicationId)}/assets/${sha256}`,
    sha256,
  );
}
