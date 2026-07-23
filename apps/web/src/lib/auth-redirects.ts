const DEFAULT_LOGIN_RETURN_PATH = "/dashboard";
const DEFAULT_LOGOUT_RETURN_PATH = "/login";

function hasUnsafeRedirectCharacters(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code <= 31 || code === 127 || value[index] === "\\") {
      return true;
    }
  }

  return false;
}

export function safeAppPath(
  value: string | null | undefined,
  fallback = DEFAULT_LOGIN_RETURN_PATH,
  origin = "http://localhost",
): string {
  if (!value || hasUnsafeRedirectCharacters(value)) {
    return fallback;
  }

  try {
    const parsed = new URL(value, origin);
    if (parsed.origin !== origin) {
      return fallback;
    }

    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}

export function safeLogoutUrl(requestUrl: string, value: string | null | undefined): string {
  const requestOrigin = new URL(requestUrl).origin;
  const path = safeAppPath(value, DEFAULT_LOGOUT_RETURN_PATH, requestOrigin);
  return new URL(path, requestOrigin).toString();
}

export function authErrorRedirectUrl(requestUrl: string): URL {
  const url = new URL("/login", requestUrl);
  url.searchParams.set("auth_error", "sign_in_failed");
  return url;
}
