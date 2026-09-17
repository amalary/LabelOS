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
