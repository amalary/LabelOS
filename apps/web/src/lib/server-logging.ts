import "server-only";

type LogSeverity = "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

type LogFields = Record<string, unknown> & {
  agent_name?: string;
  correlation_id?: string;
  duration_ms?: number;
  error_code?: string;
  error_type?: string;
  event_name?: string;
  http_method?: string;
  http_status?: number;
  job_id?: string;
  organization_id?: string;
  path?: string;
  request_id?: string;
  retry_count?: number;
  route?: string;
  span_id?: string;
  trace_header?: string;
  trace_id?: string;
  user_id?: string;
  workflow_id?: string;
};

const SENSITIVE_KEY_PARTS = [
  "authorization",
  "cookie",
  "password",
  "secret",
  "token",
  "api_key",
  "apikey",
  "access_token",
  "refresh_token",
];

const LOG_LEVELS: Record<LogSeverity, number> = {
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
  CRITICAL: 50,
};

function configuredLogLevel(): LogSeverity {
  const value = (process.env.NEXT_RUNTIME_LOG_LEVEL ?? process.env.LOG_LEVEL ?? "INFO")
    .trim()
    .toUpperCase();
  return value in LOG_LEVELS ? (value as LogSeverity) : "INFO";
}

function serviceName(): string {
  return process.env.SERVICE_NAME ?? "labelos-web";
}

function projectId(): string | undefined {
  return process.env.GOOGLE_CLOUD_PROJECT ?? process.env.GCP_PROJECT_ID;
}

function shouldLog(severity: LogSeverity): boolean {
  return LOG_LEVELS[severity] >= LOG_LEVELS[configuredLogLevel()];
}

function sanitize(value: unknown): unknown {
  if (value instanceof Error) {
    return {
      message: value.message,
      name: value.name,
      stack: value.stack,
    };
  }

  if (Array.isArray(value)) {
    return value.map(sanitize);
  }

  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, nested]) => {
        const lowerKey = key.toLowerCase();
        if (SENSITIVE_KEY_PARTS.some((part) => lowerKey.includes(part))) {
          return [key, "[REDACTED]"];
        }
        return [key, sanitize(nested)];
      }),
    );
  }

  if (typeof value === "string" && value.length > 2048) {
    return `${value.slice(0, 2048)}...[TRUNCATED]`;
  }

  return value;
}

function cloudTrace(traceHeader: string | null | undefined): LogFields {
  if (!traceHeader) {
    return {};
  }

  const [traceSpan = "", traceOptions = ""] = traceHeader.split(";", 2);
  const [traceId, spanId = ""] = traceSpan.split("/", 2);
  if (!traceId) {
    return {};
  }

  const gcpProjectId = projectId();
  return {
    trace_id: traceId,
    ...(spanId ? { span_id: spanId } : {}),
    "logging.googleapis.com/trace": gcpProjectId
      ? `projects/${gcpProjectId}/traces/${traceId}`
      : traceId,
    ...(spanId ? { "logging.googleapis.com/spanId": spanId } : {}),
    ...(traceOptions.includes("o=1") ? { "logging.googleapis.com/trace_sampled": true } : {}),
  };
}

export function logServerEvent(
  severity: LogSeverity,
  message: string,
  fields: LogFields = {},
): void {
  if (!shouldLog(severity)) {
    return;
  }

  const service = serviceName();
  const environment = process.env.APP_ENV ?? process.env.NODE_ENV ?? "local";
  const version = process.env.NEXT_PUBLIC_APP_VERSION ?? "0.0.0";
  const { trace_header: traceHeader, path, ...safeFields } = fields;
  const payload = sanitize({
    timestamp: new Date().toISOString(),
    severity,
    message,
    service,
    environment,
    version,
    labels: {
      environment,
      service,
    },
    serviceContext: {
      service,
      version,
    },
    ...(typeof path === "string" && !safeFields.route ? { route: path } : {}),
    ...cloudTrace(traceHeader),
    ...safeFields,
  });

  const line = JSON.stringify(payload);
  if (severity === "ERROR" || severity === "CRITICAL") {
    console.error(line);
  } else if (severity === "WARNING") {
    console.warn(line);
  } else {
    console.log(line);
  }
}

export function logServerError(message: string, error: unknown, fields: LogFields = {}): void {
  logServerEvent("ERROR", message, {
    ...fields,
    error,
    ...(error instanceof Error ? { stack_trace: error.stack } : {}),
  });
}
