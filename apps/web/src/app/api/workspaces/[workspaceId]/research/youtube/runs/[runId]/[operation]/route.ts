import { ApiClientError, apiFetch } from "../../../../../../../../../lib/api-client";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
type Context = { params: Promise<{ workspaceId: string; runId: string; operation: string }> };
const codes = new Set([
  "quota_exceeded",
  "rate_limited",
  "timeout",
  "data_unavailable",
  "authentication_failed",
  "provider_unavailable",
]);

async function proxy(request: Request, context: Context) {
  const { workspaceId, runId, operation } = await context.params;
  const headers = new Headers({ "Cache-Control": "no-store" });
  const allowed =
    request.method === "DELETE"
      ? operation === "display-cache"
      : ["search", "channel"].includes(operation);
  const uuid = /^[a-f0-9-]{36}$/i;
  if (!allowed || !uuid.test(workspaceId) || !uuid.test(runId))
    return new Response(null, { status: 404, headers });
  try {
    const upstream = await apiFetch(
      `/api/v1/workspaces/${workspaceId}/research/youtube/runs/${runId}/${operation}`,
      {
        method: request.method,
        headers: { "Content-Type": "application/json" },
        body: request.method === "DELETE" ? undefined : await request.text(),
      },
    );
    const retry = upstream.headers.get("retry-after");
    if (retry && /^\d{1,8}$/.test(retry)) headers.set("Retry-After", retry);
    if (upstream.status === 204) return new Response(null, { status: 204, headers });
    const body = await upstream.json();
    if (!upstream.ok)
      return Response.json(
        { detail: { code: codes.has(body.detail?.code) ? body.detail.code : "error" } },
        { status: upstream.status, headers },
      );
    return Response.json(body, { headers });
  } catch (error) {
    const status =
      error instanceof ApiClientError
        ? (error.status ?? (error.code === "network_failure" ? 502 : 401))
        : 502;
    return Response.json({ detail: { code: "error" } }, { status, headers });
  }
}
export const POST = proxy;
export const DELETE = proxy;
