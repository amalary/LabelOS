import { ApiClientError, apiFetch } from "../../../lib/api-client";

/** Error bodies can contain upstream diagnostics. Only successful safe API projections pass through. */
export async function proxyPublicationRead(path: string): Promise<Response> {
  const headers = { "Cache-Control": "no-store" };
  try {
    const upstream = await apiFetch(path, { headers: { Accept: "application/json" } });
    if (!upstream.ok) {
      return Response.json(
        { detail: "Publication history unavailable" },
        { status: upstream.status, headers },
      );
    }
    return Response.json(await upstream.json(), { headers });
  } catch (error) {
    const status =
      error instanceof ApiClientError
        ? (error.status ?? (error.code === "network_failure" ? 502 : 401))
        : 502;
    return Response.json({ detail: "Publication history unavailable" }, { status, headers });
  }
}

export async function proxyPublicationCommand(request: Request, path: string): Promise<Response> {
  const headers = { "Cache-Control": "no-store" };
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return Response.json({ detail: "Invalid recovery request" }, { status: 400, headers });
  }
  try {
    const upstream = await apiFetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "Idempotency-Key": request.headers.get("Idempotency-Key") ?? "",
      },
      body: JSON.stringify(payload),
    });
    if (!upstream.ok)
      return Response.json(
        { detail: "Publication recovery unavailable" },
        { status: upstream.status, headers },
      );
    return Response.json(await upstream.json(), { headers });
  } catch (error) {
    const status =
      error instanceof ApiClientError
        ? (error.status ?? (error.code === "network_failure" ? 502 : 401))
        : 502;
    return Response.json({ detail: "Publication recovery unavailable" }, { status, headers });
  }
}

export async function proxyPublicationAsset(path: string, digest: string): Promise<Response> {
  const headers = { "Cache-Control": "private, no-store" };
  try {
    const upstream = await apiFetch(path);
    if (!upstream.ok)
      return Response.json(
        { detail: "Prepared asset unavailable" },
        { status: upstream.status, headers },
      );
    return new Response(await upstream.arrayBuffer(), {
      headers: {
        ...headers,
        "Content-Type": "application/octet-stream",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": `attachment; filename="${digest}"`,
      },
    });
  } catch (error) {
    const status =
      error instanceof ApiClientError
        ? (error.status ?? (error.code === "network_failure" ? 502 : 401))
        : 502;
    return Response.json({ detail: "Prepared asset unavailable" }, { status, headers });
  }
}
