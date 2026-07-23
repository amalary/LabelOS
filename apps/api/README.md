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
