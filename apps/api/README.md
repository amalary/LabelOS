# Label OS API

FastAPI backend service for Label OS.

## Development

Create a virtual environment and install dependencies:

```sh
cd apps/api
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ../../packages/database
python -m pip install -e ".[dev]"
```

Run the API:

```sh
python scripts/dev.py
```

Run tests, linting, and formatting:

```sh
python -m pytest
python -m ruff check .
python -m black .
```

The API reads configuration from environment variables. Start from the root `.env.example`.

### Scheduling worker

The private Cloud Run entrypoint uses the same image with
`uvicorn labelos_api.scheduling_worker:create_worker_app --factory --host 0.0.0.0 --port 4000`.
It is separate from the user API and requires a pinned Google OIDC workload identity.
Execution defaults to disabled and remains gated on a certified Delivery receiver.
See the [worker configuration and operations runbook](../../docs/development/scheduling-worker.md)
for IAM, environment variables, local execution, rollout, shutdown, and rollback.

### PostgreSQL integration tests

Set `TEST_POSTGRES_URL` to a disposable PostgreSQL database using the asyncpg
driver, then run the marketing and approval suites:

```powershell
$env:TEST_POSTGRES_URL = "postgresql+asyncpg://labelos_test:labelos_test@127.0.0.1:5432/labelos_test"
python -m pytest tests/test_marketing_content_repository.py tests/test_marketing_content_service.py tests/test_marketing_content_api.py tests/test_marketing_content_postgres.py tests/test_approval_repository.py tests/test_approval_service.py
```

These behavioral suites run on both SQLite and PostgreSQL when configured. The
PostgreSQL-only tests exercise overlapping transactions, cached ORM state,
approval/edit races, and constraint rollback. Each PostgreSQL test creates and
drops its own randomly named schema; the test user needs permission to create
schemas. CI provisions PostgreSQL 16 and always sets this URL.

Content writers acquire a parent row lock before reading channels or revisions.
Approval mutations use the same parent-first lock order. Reconciliation plans
must be built and applied within that locked transaction; commit or rollback
releases the lock. This serializes writes while retaining the API's existing
last-write-wins behavior for full replacement payloads.

## WorkOS Webhooks

The WorkOS webhook endpoint is:

```text
POST /api/v1/webhooks/workos
```

Set `WORKOS_WEBHOOK_SECRET` to the signing secret from the WorkOS Dashboard webhook endpoint. The API reads the raw request body and verifies the `WorkOS-Signature` header before parsing the event JSON.

Supported event types:

```text
user.created
user.updated
user.deleted
organization.created
organization.updated
organization.deleted
organization_membership.created
organization_membership.updated
organization_membership.deleted
```

Local testing:

1. Start the API with `WORKOS_WEBHOOK_SECRET` set in your local `.env`.
2. Expose the API with an HTTPS tunnel, for example `ngrok http 4000`.
3. In the WorkOS Dashboard, create a webhook endpoint using `https://<your-tunnel>/api/v1/webhooks/workos`.
4. Subscribe only to the supported event types listed above.
5. Trigger a user, organization, or organization membership change in WorkOS.
6. Check the local database `webhook_events` table for the processed event ID and status.

Duplicate deliveries return `200` with `status: "duplicate"`. Unsupported signed events return `200` with `status: "ignored"` so WorkOS does not retry events that this API intentionally does not handle.

Database migrations live in `packages/database`. Run database commands from the repository root:

```sh
pnpm db:start
pnpm db:migrate
pnpm db:migration -- -m "describe change"
pnpm db:rollback
```
