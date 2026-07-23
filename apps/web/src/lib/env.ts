import "server-only";

const PLACEHOLDER_MARKERS = ["replace", "<your-", "<set-", "placeholder"];

let validated = false;

function isMissing(value: string | undefined): boolean {
  if (!value) {
    return true;
  }

  const normalized = value.trim().toLowerCase();
  return PLACEHOLDER_MARKERS.some((marker) => normalized.includes(marker));
}

function requireVariable(name: string, errors: string[]): string | undefined {
  const value = process.env[name];
  if (isMissing(value)) {
    errors.push(name);
  }
  return value;
}

export function validateWebServerEnv(): void {
  if (validated || process.env.NODE_ENV === "test") {
    return;
  }

  const errors: string[] = [];
  const cookiePassword = requireVariable("WORKOS_COOKIE_PASSWORD", errors);

  requireVariable("WORKOS_CLIENT_ID", errors);
  requireVariable("WORKOS_API_KEY", errors);
  requireVariable("WEB_BASE_URL", errors);
  requireVariable("API_BASE_URL", errors);

  const redirectUri =
    process.env.WORKOS_REDIRECT_URI ?? process.env.NEXT_PUBLIC_WORKOS_REDIRECT_URI;
  if (isMissing(redirectUri)) {
    errors.push("WORKOS_REDIRECT_URI or NEXT_PUBLIC_WORKOS_REDIRECT_URI");
  }

  if (cookiePassword && cookiePassword.length < 32) {
    errors.push("WORKOS_COOKIE_PASSWORD must be at least 32 characters");
  }

  if (errors.length > 0) {
    throw new Error(`Missing or invalid WorkOS web environment: ${errors.join(", ")}`);
  }

  validated = true;
}

export function getWorkOSRedirectUri(): string | undefined {
  return process.env.WORKOS_REDIRECT_URI ?? process.env.NEXT_PUBLIC_WORKOS_REDIRECT_URI;
}
