import { proxyPublicationRead } from "../../publications-proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request, context: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await context.params;
  const input = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const key of ["content_item_id", "limit", "after_id"]) {
    const value = input.get(key);
    if (value !== null) query.set(key, value);
  }
  return proxyPublicationRead(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/publications?${query}`,
  );
}
