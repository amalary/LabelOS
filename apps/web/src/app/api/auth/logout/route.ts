import { NextRequest, NextResponse } from "next/server";

import { ACCESS_TOKEN_COOKIE } from "../../../../lib/auth";

export function POST(request: NextRequest) {
  const response = NextResponse.redirect(new URL("/login", request.url));
  response.cookies.delete(ACCESS_TOKEN_COOKIE);
  return response;
}
