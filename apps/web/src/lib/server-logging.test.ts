import { beforeEach, describe, expect, it, vi } from "vitest";

describe("server logging", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.spyOn(console, "log").mockImplementation(() => undefined);
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });

  it("emits structured Cloud Logging-compatible JSON", async () => {
    vi.stubEnv("APP_ENV", "test");
    vi.stubEnv("SERVICE_NAME", "labelos-web");
    vi.stubEnv("NEXT_PUBLIC_APP_VERSION", "1.2.3");
    const { logServerEvent } = await import("./server-logging");

    logServerEvent("INFO", "route completed", {
      path: "/dashboard",
      trace_header: "trace-123/span-456;o=1",
    });

    expect(console.log).toHaveBeenCalledTimes(1);
    const payload = JSON.parse(vi.mocked(console.log).mock.calls[0]?.[0] as string);
    expect(payload).toMatchObject({
      environment: "test",
      message: "route completed",
      route: "/dashboard",
      service: "labelos-web",
      severity: "INFO",
      span_id: "span-456",
      trace_id: "trace-123",
      version: "1.2.3",
      serviceContext: {
        service: "labelos-web",
        version: "1.2.3",
      },
    });
    expect(payload.trace_header).toBeUndefined();
  });

  it("redacts sensitive metadata before logging errors", async () => {
    const { logServerError } = await import("./server-logging");

    logServerError("onboarding failed", new Error("WorkOS unavailable"), {
      authorization: "Bearer secret",
      metadata: { refresh_token: "secret-refresh-token", safe: "value" },
    });

    expect(console.error).toHaveBeenCalledTimes(1);
    const payload = JSON.parse(vi.mocked(console.error).mock.calls[0]?.[0] as string);
    expect(payload.authorization).toBe("[REDACTED]");
    expect(payload.metadata).toEqual({ refresh_token: "[REDACTED]", safe: "value" });
    expect(payload.error).toMatchObject({
      message: "WorkOS unavailable",
      name: "Error",
    });
    expect(payload.stack_trace).toContain("WorkOS unavailable");
  });
});
