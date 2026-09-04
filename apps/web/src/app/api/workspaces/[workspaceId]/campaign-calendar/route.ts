import { proxyWorkspaceRequest } from "../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const preservedQueryParams = new Set([
  "start",
  "end",
  "timezone",
  "campaign_id",
  "artist_id",
  "release_id",
  "status",
  "event_types",
  "include_archived",
  "include_published",
  "limit",
  "offset",
]);

function campaignCalendarQuery(url: string): string {
  const source = new URL(url).searchParams;
  const params = new URLSearchParams();
  for (const [key, value] of source.entries()) {
    if (preservedQueryParams.has(key)) {
      params.append(key, value);
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function GET(request: Request, context: { params: Promise<{ workspaceId: string }> }) {
  const query = campaignCalendarQuery(request.url);
  return context.params.then(({ workspaceId }) =>
    proxyWorkspaceRequest(`/api/v1/workspaces/${workspaceId}/campaign-calendar${query}`, {
      headers: {
        Accept: "application/json",
      },
    }),
  );
}
