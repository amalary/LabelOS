import { NextRequest } from "next/server";

import { proxyProfileRequest } from "../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ workspaceId: string }> },
) {
  const { workspaceId } = await context.params;
  const upstreamPath = new URL(`/api/v1/workspaces/${workspaceId}/profiles`, "http://local");
  const limit = request.nextUrl.searchParams.get("limit");
  const offset = request.nextUrl.searchParams.get("offset");
  if (limit) {
    upstreamPath.searchParams.set("limit", limit);
  }
  if (offset) {
    upstreamPath.searchParams.set("offset", offset);
  }

  return proxyProfileRequest(`${upstreamPath.pathname}${upstreamPath.search}`, {
    headers: {
      Accept: "application/json",
    },
  });
}
