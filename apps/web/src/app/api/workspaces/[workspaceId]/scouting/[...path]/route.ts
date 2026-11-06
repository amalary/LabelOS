import { ApiClientError, apiFetch } from "../../../../../../lib/api-client";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
type Context = { params: Promise<{ workspaceId: string; path: string[] }> };
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;

async function proxy(request: Request, context: Context) {
  const { workspaceId, path } = await context.params;
  const headers = { "Cache-Control": "no-store" };
  const valid =
    uuid.test(workspaceId) &&
    ((path.length === 1 && path[0] === "runs" && request.method === "GET") ||
      (path.length === 1 && path[0] === "local-session" && request.method === "POST") ||
      (path[0] === "candidates" &&
        ((path.length === 1 && ["GET", "POST"].includes(request.method)) ||
          (path.length === 2 &&
            uuid.test(path[1] ?? "") &&
            ["GET", "PATCH", "DELETE"].includes(request.method)) ||
          (path.length === 3 &&
            uuid.test(path[1] ?? "") &&
            path[2] === "source" &&
            request.method === "DELETE"))));
  if (!valid) return new Response(null, { status: 404, headers });
  try {
    const query = new URL(request.url).searchParams;
    const safeQuery = new URLSearchParams();
    for (const name of ["status", "limit", "offset"]) {
      if (query.has(name)) safeQuery.set(name, query.get(name)!);
    }
    const upstream = await apiFetch(
      `/api/v1/workspaces/${workspaceId}/scouting/${path.join("/")}?${safeQuery}`,
      {
        method: request.method,
        headers: { "Content-Type": "application/json" },
        body: ["POST", "PATCH"].includes(request.method) ? await request.text() : undefined,
      },
    );
    if (upstream.status === 204) return new Response(null, { status: 204, headers });
    if (!upstream.ok)
      return Response.json(
        { error: "Scouting request failed" },
        { status: upstream.status, headers },
      );
    return Response.json(await upstream.json(), { status: upstream.status, headers });
  } catch (error) {
    return Response.json(
      { error: "Scouting request failed" },
      { status: error instanceof ApiClientError ? (error.status ?? 401) : 502, headers },
    );
  }
}
export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
