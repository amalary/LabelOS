import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const PLACEHOLDER_MARKERS = ["replace", "placeholder", "<", ">"];
const REQUIRED_ENV = [
  "AUTH_PROVIDER",
  "WORKOS_CLIENT_ID",
  "WORKOS_API_KEY",
  "WORKOS_COOKIE_PASSWORD",
  "WORKOS_WEBHOOK_SECRET",
  "WORKOS_REDIRECT_URI",
  "WEB_BASE_URL",
  "API_BASE_URL",
  "DATABASE_URL",
];

function loadDotEnv() {
  const path = resolve(process.cwd(), ".env");
  let contents = "";
  try {
    contents = readFileSync(path, "utf8");
  } catch {
    return;
  }

  for (const line of contents.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }
    const separator = trimmed.indexOf("=");
    if (separator <= 0) {
      continue;
    }
    const key = trimmed.slice(0, separator).trim();
    const value = trimmed.slice(separator + 1).trim().replace(/^['"]|['"]$/g, "");
    if (!(key in process.env)) {
      process.env[key] = value;
    }
  }
}

function isPlaceholder(value) {
  const normalized = value.trim().toLowerCase();
  return PLACEHOLDER_MARKERS.some((marker) => normalized.includes(marker));
}

function statusFor(name) {
  const value = process.env[name];
  if (!value || !value.trim()) {
    return "missing";
  }
  if (isPlaceholder(value)) {
    return "placeholder";
  }
  return "present";
}

function validateEnvironment() {
  const failures = [];
  const statuses = new Map();

  for (const name of REQUIRED_ENV) {
    const status = statusFor(name);
    statuses.set(name, status);
    if (status !== "present") {
      failures.push(`${name} is ${status}`);
    }
  }

  if (statusFor("NEXT_PUBLIC_WORKOS_REDIRECT_URI") !== "present") {
    failures.push("NEXT_PUBLIC_WORKOS_REDIRECT_URI is missing or placeholder");
  }

  if ((process.env.AUTH_PROVIDER ?? "").toLowerCase() !== "workos") {
    failures.push("AUTH_PROVIDER must be workos");
  }

  const cookiePassword = process.env.WORKOS_COOKIE_PASSWORD ?? "";
  if (cookiePassword && !isPlaceholder(cookiePassword) && cookiePassword.length < 32) {
    failures.push("WORKOS_COOKIE_PASSWORD must be at least 32 characters");
  }

  const webBaseUrl = process.env.WEB_BASE_URL;
  const redirectUri =
    process.env.WORKOS_REDIRECT_URI ?? process.env.NEXT_PUBLIC_WORKOS_REDIRECT_URI;
  if (webBaseUrl && redirectUri && !redirectUri.startsWith(webBaseUrl)) {
    failures.push("WORKOS_REDIRECT_URI must use WEB_BASE_URL as its origin");
  }

  return { failures, statuses };
}

async function fetchStatus(url, expectedStatuses = [200]) {
  const response = await fetch(url, { redirect: "manual" });
  if (!expectedStatuses.includes(response.status)) {
    throw new Error(`${url} returned ${response.status}`);
  }
  return response.status;
}

async function runLiveProbes() {
  const apiBaseUrl = process.env.API_BASE_URL;
  const webBaseUrl = process.env.WEB_BASE_URL;
  if (!apiBaseUrl || !webBaseUrl) {
    throw new Error("WEB_BASE_URL and API_BASE_URL are required for --live");
  }

  const probes = [
    ["API health", `${apiBaseUrl}/health`, [200]],
    ["API database health", `${apiBaseUrl}/health/database`, [200]],
    ["Web health", `${webBaseUrl}/api/health`, [200]],
    ["WorkOS login redirect", `${webBaseUrl}/api/auth/login`, [303, 307, 308]],
  ];

  for (const [label, url, statuses] of probes) {
    const status = await fetchStatus(url, statuses);
    console.log(`${label}: PASS (${status})`);
  }
}

async function main() {
  loadDotEnv();

  const live = process.argv.includes("--live");
  const { failures, statuses } = validateEnvironment();

  console.log("Organization acceptance preflight");
  for (const [name, status] of statuses) {
    console.log(`${name}: ${status}`);
  }
  console.log(`NEXT_PUBLIC_WORKOS_REDIRECT_URI: ${statusFor("NEXT_PUBLIC_WORKOS_REDIRECT_URI")}`);

  if (failures.length > 0) {
    console.error("\nPreflight failed:");
    for (const failure of failures) {
      console.error(`- ${failure}`);
    }
    process.exitCode = 1;
    return;
  }

  if (live) {
    await runLiveProbes();
  }

  console.log(live ? "Preflight and live probes passed." : "Preflight passed.");
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
