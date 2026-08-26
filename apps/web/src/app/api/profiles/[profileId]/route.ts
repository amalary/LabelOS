import { proxyProfileRequest } from "../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(_request: Request, context: { params: Promise<{ profileId: string }> }) {
  return context.params.then(({ profileId }) =>
    proxyProfileRequest(`/api/v1/profiles/${profileId}`, {
      headers: {
        Accept: "application/json",
      },
    }),
  );
}
