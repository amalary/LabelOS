import { NextRequest } from "next/server";

import { requireAccessTokenForApi } from "../../../../../../lib/auth-token.server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ organizationId: string }> },
) {
  const { organizationId } = await context.params;
  const upstreamUrl = new URL(
    `/api/v1/realtime/organizations/${organizationId}/events`,
    apiBaseUrl,
  );
  const lastEventId = request.nextUrl.searchParams.get("lastEventId");
  if (lastEventId) {
    upstreamUrl.searchParams.set("lastEventId", lastEventId);
  }

  const accessToken = await requireAccessTokenForApi();
  const upstream = await fetch(upstreamUrl, {
    cache: "no-store",
    headers: {
      Accept: "text/event-stream",
      Authorization: `Bearer ${accessToken}`,
      "X-Request-ID": request.headers.get("x-request-id") ?? crypto.randomUUID(),
    },
    signal: request.signal,
  });

  if (!upstream.ok || !upstream.body) {
    return Response.json(
      { detail: "Realtime subscription failed" },
      { status: upstream.status || 502 },
    );
  }

  return new Response(upstream.body, {
    headers: {
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "Content-Type": "text/event-stream",
      "X-Accel-Buffering": "no",
    },
    status: 200,
  });
}
