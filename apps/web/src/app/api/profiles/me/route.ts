import { NextRequest } from "next/server";

import { proxyProfileRequest } from "../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET() {
  return proxyProfileRequest("/api/v1/profiles/me", {
    headers: {
      Accept: "application/json",
    },
  });
}

export async function PATCH(request: NextRequest) {
  return proxyProfileRequest("/api/v1/profiles/me", {
    body: await request.text(),
    headers: {
      Accept: "application/json",
      "Content-Type": request.headers.get("content-type") ?? "application/json",
    },
    method: "PATCH",
  });
}
