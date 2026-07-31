# Observability

LabelOS uses stdout/stderr structured logging as the primary observability path.
This fits Cloud Run because the runtime collects container output and forwards it
to Google Cloud Logging without application credentials or a logging sidecar.

## Runtime Coverage

- `apps/api`: FastAPI request logging, exception handlers, Cloud Logging JSON.
- `apps/agents`: FastAPI request logging, exception handlers, Cloud Logging JSON.
- `apps/web`: Next.js server-side JSON logs for handled runtime failures.
- Cloud Run request logs remain the source of truth for ingress latency,
  response codes, instance metadata, and revision labels.

There are no background workers or scheduled jobs in the repository today. When
they are added, they should use the same JSON shape and service labels.

## Log Shape

Application logs include:

- `severity`, `message`, `timestamp`.
- `service`, `environment`, `version`, `labels`.
- `serviceContext` for Google Cloud Error Reporting grouping.
- `httpRequest`, `route`, `http_method`, `http_status`, and `duration_ms` on
  FastAPI request logs.
- `logging.googleapis.com/trace`, `trace_id`, `span_id`, and sampled flag when
  Cloud Run sends `X-Cloud-Trace-Context`.
- `logging.googleapis.com/insertId` and `request_id` when an `X-Request-ID` is
  present or generated.
- `stack_trace` for logged exceptions.

Sensitive metadata keys are redacted before logging. Redaction currently covers
authorization headers, cookies, passwords, secrets, tokens, API keys, refresh
tokens, access tokens, and database URLs.

## Environment Variables

- `APP_ENV`: local, test, staging, production, or equivalent environment label.
- `APP_VERSION`: deployed application version for Python services.
- `LOG_LEVEL`: default runtime log level.
- `LOG_FORMAT`: `json` by default; `text` is available for local Python service
  debugging only. Non-local environments always emit JSON.
- `SERVICE_NAME`: service label for the current Cloud Run service.
- `AGENTS_SERVICE_NAME`: agent service override.
- `NEXT_PUBLIC_APP_VERSION`: deployed application version for the Next.js server
  logger.
- `NEXT_RUNTIME_LOG_LEVEL`: Next.js server logger level.
- `GCP_PROJECT_ID` or `GOOGLE_CLOUD_PROJECT`: enables fully qualified Cloud
  Trace resource names in log entries.

Do not place secrets in these variables. Monitoring credentials, if ever needed,
should be mounted from Secret Manager.

## Google Cloud Operations

Recommended production setup:

- Cloud Logging: use structured log filters by `service`, `environment`,
  `severity`, `httpRequest.status`, and `request_id`.
- Error Reporting: enable the Cloud Run services and use entries with
  `serviceContext` and `stack_trace` for grouping.
- Cloud Monitoring: create dashboards and alerts from Cloud Run metrics and log
  based metrics.
- Cloud Trace/OpenTelemetry: defer until there are enough cross-service flows to
  justify instrumentation beyond Cloud Run trace correlation.

Suggested alerts:

- API 5xx rate above normal baseline.
- Web 5xx rate above normal baseline.
- Agent 5xx rate above normal baseline.
- Container restart count increases.
- Database health endpoint failure from a private uptime check.
- Error Reporting issue count spike.

Do not expose new public monitoring endpoints. Existing `/health` endpoints are
for service health checks only.
