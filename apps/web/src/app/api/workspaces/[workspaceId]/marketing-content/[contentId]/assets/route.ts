import { ApiClientError, apiFetch } from "../../../../../../../lib/api-client";

const MAX_BYTES = 16 * 1024 * 1024;
const headers = { "Cache-Control": "no-store" };
const failure = (status: number) =>
  Response.json({ detail: "Unable to upload media" }, { status, headers });

export async function POST(
  request: Request,
  context: { params: Promise<{ workspaceId: string; contentId: string }> },
): Promise<Response> {
  const { workspaceId, contentId } = await context.params;
  const mediaType = request.headers.get("content-type")?.toLowerCase() ?? "";
  if (!/^(image|video|audio)\/[a-z0-9][a-z0-9.+-]{0,63}$/.test(mediaType)) return failure(415);
  const declared = request.headers.get("content-length");
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > MAX_BYTES))
    return failure(413);
  const reader = request.body?.getReader();
  if (!reader) return failure(400);
  try {
    // Buffer a bounded body so apiFetch can safely retry authentication once.
    const chunks: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BYTES) {
        await reader.cancel();
        return failure(413);
      }
      chunks.push(value);
    }
    if (!size) return failure(400);
    const body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      body.set(chunk, offset);
      offset += chunk.byteLength;
    }
    const upstream = await apiFetch(
      `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/marketing-content/${encodeURIComponent(contentId)}/assets`,
      { method: "POST", headers: { "Content-Type": mediaType }, body },
    );
    if (!upstream.ok) return failure(upstream.status);
    return Response.json(await upstream.json(), { headers });
  } catch (error) {
    return failure(
      error instanceof ApiClientError
        ? (error.status ?? (error.code === "network_failure" ? 502 : 401))
        : 502,
    );
  } finally {
    reader.releaseLock();
  }
}
