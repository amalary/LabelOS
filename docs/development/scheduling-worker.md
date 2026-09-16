# Trusted Scheduling Engine worker

The worker is a separate Cloud Run service using the existing API Docker image.
Start `labelos_api.scheduling_worker:create_worker_app` with Uvicorn's `--factory`.
It exposes `POST /internal/scheduling/run-due` and a process-only `/health` check.
The normal FastAPI application does not mount this endpoint. There are no user
routes, CORS permissions, API docs, background loops, queues, or migrations here.
`infrastructure/` has no provisioning conventions beyond `.gitkeep`; this change
does not create GCP resources. The steps below are an operator runbook.

Each invocation sweeps **one deployment-configured workspace**: at most one batch
of expired leases, one batch of due candidates, and one attempt per claim. The two
batch budgets are independent. Use another narrowly scoped worker deployment if
another workspace needs execution; there is no unbounded tenant discovery pass.

## Workload identity gate

Use two dedicated, user-managed accounts in the target project:

| Identity                                                        | Purpose and permissions                                                                                                                                                                                                                             |
| --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `labelos-scheduling-invoker@PROJECT_ID.iam.gserviceaccount.com` | Cloud Scheduler's OIDC caller; grant `roles/run.invoker` on **only this worker service**. Pin its email and numeric `uniqueId` in worker configuration. No application DB or provider access.                                                       |
| `labelos-scheduling-runtime@PROJECT_ID.iam.gserviceaccount.com` | Attach as the worker Cloud Run runtime service account. Grant access only to the worker DB connection secret and required database connectivity (including Cloud SQL Client if using Cloud SQL). No provider credentials or publishing permissions. |

Keep the Cloud Run Invoker IAM check enabled. Do not grant `allUsers`,
`allAuthenticatedUsers`, ordinary users, or the web/API runtime invocation access.
Restrict who may impersonate the Invoker account: that permission grants workload
authority. The application separately verifies the Google RS256 signature, issuer,
exact audience, expiry/issued-at, exact account email, numeric subject, and boolean
`email_verified=true`. A recreated account with the same email has a different
subject and is denied. WorkOS tokens, user roles, unsigned tokens, scheduler
headers, and `actor=None` grant no authority.

Set `SCHEDULING_WORKER_OIDC_AUDIENCE` to the worker's canonical HTTPS `run.app`
origin, exactly as returned by Cloud Run, **without trailing slash, path or query**.
Set Cloud Scheduler's OIDC audience to that identical value; the target URL adds
`/internal/scheduling/run-due`. Use its generated `Authorization: Bearer` header.
The worker requires the full signed token; it never trusts decoded platform
headers. `X-Serverless-Authorization` alone is not supported: Cloud Run can remove
its signature. For a custom caller using that header for IAM, also send the full
signed token in `Authorization`.

These IAM and audience requirements follow Google's
[Cloud Run service authentication documentation](https://docs.cloud.google.com/run/docs/authenticating/service-to-service).
Operators must inspect the deployed IAM policy and attached runtime identity;
application startup cannot prove those control-plane settings.

## Configuration

All settings are server environment variables; request bodies cannot override
scope, identity, controls, batch limits, receivers, or timing. Bodies are ignored
and never logged by worker code. Use an empty POST.

| Variable                                    | Default / requirement                                                                                                                                   |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `APP_ENV`                                   | Set `production`; Cloud Run rejects local/test environment labels.                                                                                      |
| `SCHEDULING_EXECUTION_ENABLED`              | `false`; deployment execution switch.                                                                                                                   |
| `SCHEDULING_WORKER_AUTH_MODE`               | `google-oidc`; required for HTTP in every environment. `local-cli` is command-only. Other modes are invalid.                                            |
| `SCHEDULING_WORKER_SERVICE_ACCOUNT_EMAIL`   | Required Invoker account email.                                                                                                                         |
| `SCHEDULING_WORKER_SERVICE_ACCOUNT_SUBJECT` | Required numeric account `uniqueId`, not project number. Retrieve with `gcloud iam service-accounts describe ACCOUNT_EMAIL --format='value(uniqueId)'`. |
| `SCHEDULING_WORKER_OIDC_AUDIENCE`           | Required canonical worker service origin.                                                                                                               |
| `SCHEDULING_WORKER_WORKSPACE_ID`            | Required single authorized workspace UUID.                                                                                                              |
| `SCHEDULING_WORKER_BATCH_SIZE`              | `25`; range 1–1000 per recovery/claim pass.                                                                                                             |
| `SCHEDULING_WORKER_LEASE_SECONDS`           | `120`; range 1–3600; must exceed sweep timeout.                                                                                                         |
| `SCHEDULING_WORKER_LATENESS_SECONDS`        | `300`; range 0–86400; older jobs block rather than publish late.                                                                                        |
| `SCHEDULING_WORKER_TIMEOUT_SECONDS`         | `30`; range 1–300; cancels and awaits the sweep.                                                                                                        |
| `DELIVERY_RECEIVER_BACKEND`                 | `unavailable` is currently the only deployable value. Fake/successful test receivers are rejected at startup.                                           |
| `DATABASE_URL`                              | PostgreSQL asyncpg connection, delivered through a runtime secret.                                                                                      |
| `DATABASE_ECHO`                             | Must be `false` to keep SQL parameters out of logs.                                                                                                     |
| `LOG_LEVEL`, `LOG_FORMAT`                   | Use `INFO`, `json`. Worker log service name is `labelos-scheduling-worker`.                                                                             |

No shared worker secret or service-account key is needed. Scheduler mints short-lived
OIDC tokens; Cloud Run runtime uses its attached identity. Keep the DB secret in
Secret Manager and reference a reviewed version through Cloud Run secret injection.
Do not commit credentials, place tokens in scheduler bodies, or log bearer headers.
The worker does not require WorkOS, YouTube OAuth, or provider-credential secrets.
Google public signing keys are fetched from a fixed HTTPS endpoint with a five-second
authentication deadline; key-service failure denies execution with 503.

## Deployment and safe rollout

1. Review migrations through `202609152100` and the certified transactional Delivery
   receiver gate. **Today no certified production receiver exists: deploy disabled
   only.** Setting execution true returns `receiver_unavailable` before database
   access. Do not bypass this by wiring a successful fake. A future adapter must
   pass the transactional acceptance contract tests before enablement.
2. Have the platform operator create/review the accounts and IAM bindings above.
   Deploy the existing API image as a separate service using the runtime account,
   required IAM authentication, private database connectivity, min instances 0,
   concurrency 1, and initially max instances 1. Scaling limits are cost controls;
   correctness comes from PostgreSQL locks, leases, fencing, and inbox keys.
3. Override container command to `uvicorn`, with arguments
   `labelos_api.scheduling_worker:create_worker_app --factory --host 0.0.0.0 --port 4000`.
   Configure Cloud Run container port 4000, matching the existing image health check.
   Set Cloud Run request timeout to 60 seconds for the default 30-second sweep.
   Leave room for authentication (5 seconds), connection cleanup, and cold starts;
   increase the platform timeout if increasing the sweep deadline. Cloud Run's
   request timeout alone does not stop application work.
4. For first deployment, use the deterministic service origin
   `https://SERVICE_NAME-PROJECT_NUMBER.REGION.run.app` with a short service name.
   After deployment, read back the service URL with
   `gcloud run services describe SERVICE --region REGION --format='value(status.url)'`
   and reconcile the worker and Scheduler audience to that exact origin before
   invoking. This keeps the worker factory and disabled controls in place during
   bootstrap. Google documents the service URL formats in its
   [HTTPS invocation guide](https://docs.cloud.google.com/run/docs/triggering/https-request).
5. Keep `SCHEDULING_EXECUTION_ENABLED=false` and every workspace DB execution
   control false/missing. Verify an anonymous request fails at IAM, a signed token
   from a different account fails, and an authorized empty POST returns
   `execution_disabled` with correlation/worker IDs. Verify signature preservation
   through the real Cloud Run boundary. Local tests do not validate deployed IAM.
6. Prepare a paused Cloud Scheduler HTTP job, POSTing to the worker endpoint with
   the Invoker account's OIDC token and explicit audience. Recommend `* * * * *`
   (every minute), UTC, 60-second attempt deadline, and no rapid retries initially
   (`retry-count=0`); the next sweep handles recovery. Review batch capacity and
   lateness together: sustained backlog can exceed the five-minute default window.
7. Only after receiver certification, enable the deployment switch on a reviewed
   revision, then explicitly enable the selected workspace's durable control,
   manually run one sweep, inspect aggregate outcomes/audit transitions, and resume
   the scheduler. Never mass-enable workspaces during migration or startup.

The Scheduler caller account must belong to its job's project. The job creator
needs `iam.serviceAccounts.actAs` on that account. Preserve the Cloud Scheduler
service agent's `roles/cloudscheduler.serviceAgent`; do not use the service agent
itself as the caller. See Google's
[HTTP target authentication guide](https://docs.cloud.google.com/scheduler/docs/http-target-auth).

## Responses, timeouts, and duplicates

Successful completion returns `status`, `correlation_id`, `worker_id`, `claimed`,
`recovered`, and fixed-code aggregate `outcomes`. No job IDs, workspace IDs,
destinations, content, receipts, credentials, SQL, or exception text are returned.
`x-request-id` carries the existing validated correlation header or a generated UUID.
Worker IDs combine a stable UUID derived from the verified Google subject with a
fresh invocation UUID. Existing job handoff correlation remains stable across retries.

Disabled deployment/durable controls return HTTP 200 with `execution_disabled` or
`execution_refused`. Missing receiver and unexpected failures return 503; sweep
timeout returns 504. These responses omit counts when committed work may be
unknown. Authentication uses 401/403, or 503 when verification is unavailable.
Authenticated sweep logs contain IDs, status, and safe aggregate counts.

Cancellation unwinds the current transaction; earlier transactions may already be
committed. Unfinished claims remain leased until recovery. A receiver must not
swallow cancellation, commit independently, or perform external publishing I/O.
Timeout cleanup is cooperative and can extend beyond the deadline while a database
rollback completes. Configure database statement/lock timeouts operationally too.

Duplicate/overlapping requests are safe without HTTP request deduplication. Each
uses a distinct worker instance; committed inbox acceptance is deduplicated by the
existing job idempotency key. Reusing a correlation ID does not acquire execution
authority, suppress work, or change that key.

## Emergency shutdown and rollback

1. **Disable durable execution before rolling back code or schema.** In the trusted
   database operator session, update the scoped workspace control and commit:

   ```sql
   UPDATE scheduling_execution_controls
   SET execution_enabled = false
   WHERE workspace_id = '<reviewed-workspace-uuid>';
   ```

   Missing rows are already disabled. For a system-wide stop, explicitly review an
   update covering every enabled control. Wait for commit: its exclusive row lock
   serializes with worker transactions, including in-flight acceptance. This cannot
   undo delivery already accepted before the stop; Delivery has its own controls.

2. Pause the Cloud Scheduler job. Set `SCHEDULING_EXECUTION_ENABLED=false` on the
   worker revision and verify traffic/tags; revoke Invoker permission if needed.
   Pausing Scheduler or changing a revision alone does not cancel an active sweep.
3. Confirm the DB controls remain false, allow active sweeps to finish/cancel,
   inspect logs and outstanding leases/receipts. Retain claims and idempotency data;
   never clear fences or requeue by hand to accelerate rollback.
4. Roll back only after execution is disabled. Keep the DB control migration and
   handoff records intact while any worker revision can still run. Prefer code-only
   rollback; dropping execution controls removes the durable stop mechanism.
5. After recovery, repeat the rollout checks. Re-enable execution explicitly, last;
   never inherit a previous revision's enabled flag by accident.

## Explicit local execution

From `apps/api`, with a migrated disposable PostgreSQL database on loopback:

```powershell
$env:APP_ENV = 'local'
$env:SCHEDULING_WORKER_AUTH_MODE = 'local-cli'
$env:SCHEDULING_WORKER_WORKSPACE_ID = '<local-workspace-uuid>'
$env:SCHEDULING_EXECUTION_ENABLED = 'false'
python -m labelos_api.scheduling_worker --execute
```

The explicit process command uses a distinct local workload principal; it does
not impersonate a user or expose an unauthenticated HTTP route. It rejects remote
database hosts, production/test environment labels, and Cloud Run environment
markers. Deployment and durable switches still apply. With the current receiver,
enabling the deployment flag safely reports unavailable; use the test fixtures to
exercise successful delivery, never a deployment-selectable fake receiver.

## Verification

From `apps/api`, with `TEST_POSTGRES_URL` set to disposable PostgreSQL:

```powershell
python -m pytest tests/test_scheduling_worker.py tests/test_scheduling_processor_postgres.py tests/test_scheduling_processor_migration.py -q
```

Tests use real RSA signatures against a stubbed Google JWKS transport, exercise
configuration/identity rejection, local CLI gates, timeout cancellation and safe
responses, then run overlapping HTTP requests and timeout/lease recovery against
isolated PostgreSQL schemas. PostgreSQL cases skip if the test URL is absent; CI
supplies it. No test mints Google credentials or changes deployed IAM.
