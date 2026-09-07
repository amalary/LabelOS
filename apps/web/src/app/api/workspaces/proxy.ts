import { ApiClientError, apiFetch } from "../../../lib/api-client";

function responseHeaders(contentType = "application/json", upstream?: Response) {
  const headers = new Headers({
    "Cache-Control": "no-store",
    "Content-Type": contentType,
  });
  const location = upstream?.headers.get("location");
  if (location) {
    headers.set("Location", location);
  }
  return headers;
}

export async function proxyWorkspaceRequest(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  try {
    const upstream = await apiFetch(path, init);
    const body = upstream.status === 204 ? null : await upstream.text();
    return new Response(body, {
      headers: responseHeaders(upstream.headers.get("content-type") ?? "application/json", upstream),
      status: upstream.status,
    });
  } catch (error) {
    if (error instanceof ApiClientError) {
      return Response.json(
        { detail: error.message, code: error.code },
        { status: error.status ?? 401 },
      );
    }

    return Response.json({ detail: "Workspace request failed" }, { status: 502 });
  }
}
