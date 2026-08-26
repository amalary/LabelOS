import { NextRequest } from "next/server";

import { proxyProfileRequest } from "../../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ workspaceId: string }> },
) {
  const { workspaceId } = await context.params;
  const upstreamPath = new URL(`/api/v1/workspaces/${workspaceId}/people`, "http://local");
  for (const key of ["query", "limit", "offset"]) {
    const value = request.nextUrl.searchParams.get(key);
    if (value) {
      upstreamPath.searchParams.set(key, value);
    }
  }

  return proxyProfileRequest(`${upstreamPath.pathname}${upstreamPath.search}`, {
    headers: {
      Accept: "application/json",
    },
  });
}
