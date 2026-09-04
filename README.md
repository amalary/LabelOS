# Label OS

Label OS is an AI-powered operating system for record labels.

The product vision is to give labels one connected workspace for artist discovery, A&R workflows, release planning, marketing campaigns, analytics, royalties, contracts, AI agents, approval queues, and human-in-the-loop operations. The system should help teams move faster while keeping creative, financial, legal, and operational decisions reviewable by people.

## Project Status

This repository has moved beyond foundation setup into the first production
application slices. It now contains:

- A protected Next.js workspace app with WorkOS AuthKit authentication.
- A FastAPI backend with workspace-scoped authorization, roles, departments, and
  capability checks.
- PostgreSQL data models and Alembic migrations for identity, profiles,
  workspaces, campaigns, marketing content, approvals, analytics, realtime
  events, and role/capability administration.
- A dashboard with organization context, KPI cards, analytics surfaces, release
  pipeline summaries, and realtime recent activity.
- Campaign planning primitives, relationship management, goals, milestones,
  Campaign Calendar projections, and Marketing Hub content scheduling.
- Approval Queue workflows for marketing content review, decision history,
  reviewer assignment, stale revision handling, and scheduling eligibility.
- A non-production AI agent service scaffold with deterministic mock agents.

Production AI model workflows and external provider integrations are
intentionally not present yet.

## Prerequisites

- Node.js 22.23.1
- Corepack enabled for pnpm
- Python 3.12 or newer
- Docker Desktop or Docker Engine with Docker Compose for local PostgreSQL

Use the Node.js version declared in `.nvmrc` and `.node-version`, then enable pnpm through Corepack:

```sh
nvm use
corepack enable
corepack prepare pnpm@10.13.1 --activate
pnpm install
```

On Windows, `fnm` is the recommended version manager:

```powershell
fnm use
corepack enable
corepack prepare pnpm@10.13.1 --activate
pnpm install
```

## Monorepo Structure

```text
apps/
  web/       Next.js workspace app, API proxies, AuthKit routes, and UI surfaces.
  api/       FastAPI backend service and domain APIs.
  agents/    Future AI agent runtimes and workers.

packages/
  ui/        Shared interface components and design primitives.
  database/  SQLAlchemy models, Alembic migrations, and data access utilities.
  config/    Shared configuration for apps and packages.

infrastructure/  Deployment and infrastructure-as-code assets.
docs/            Product and engineering documentation.
scripts/         Repository automation scripts.
tests/           Cross-package and integration test assets.
```

Planned packages such as shared auth helpers, AI provider utilities, and shared
domain types should be added when product code needs them.

Workspaces are discovered from:

- `apps/*`
- `packages/*`

## Workspace Commands

Run commands from the repository root:

```sh
pnpm dev
pnpm api:dev
pnpm api:test
pnpm api:lint
pnpm api:format
pnpm agents:test
pnpm agents:lint
pnpm agents:health
pnpm build
pnpm lint
pnpm format
pnpm format:check
pnpm typecheck
pnpm test
pnpm clean
```

## Frontend Setup

The frontend lives in `apps/web` and uses Next.js, React, TypeScript, the App Router, Tailwind CSS, and ESLint.

Environment configuration is read from root-level `.env` files. Start from the safe template:

```sh
cp .env.example .env
```

For local frontend development, set:

```sh
NEXT_PUBLIC_API_URL=http://localhost:4000
NEXT_PUBLIC_WORKOS_REDIRECT_URI=http://localhost:3000/api/auth/callback
WEB_BASE_URL=http://localhost:3000
```

`NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WORKOS_REDIRECT_URI` are intentionally
public and must not contain secrets. WorkOS secrets and access tokens are read
only by server-side route handlers, server components, and the API.

Run the frontend through the root workspace commands:

```sh
pnpm dev
pnpm build
pnpm lint
pnpm typecheck
```

The frontend currently provides:

- `/` - starter landing placeholder.
- `/dashboard` - protected Dashboard V1 with organization-aware header,
  permission-aware KPI cards, label performance, release pipeline, and realtime
  recent activity.
- `/analytics` and `/workspace/analytics` - analytics read/configuration
  surfaces.
- `/artists` and `/artists/[artistProfileId]` - artist profile workspace and
  editor surfaces.
- `/campaigns` and `/campaigns/[campaignId]` - campaign list and detail
  workspace surfaces.
- `/marketing` - Marketing Hub with the content-specific operational calendar,
  drafts, Approval Queue, and account placeholders.
- `/campaign-calendar` - read-only cross-campaign operational timeline built
  from canonical Campaign, Marketing Content, Approval, Artist/Profile, and
  Release data.
- `/profile`, `/workspace/people`, and `/workspace/settings` - profile, people,
  invite, role, and access management surfaces.
- `/login` - starts the server-side WorkOS AuthKit flow.

The `/dashboard` route is protected by AuthKit middleware. Users without a valid
AuthKit session are redirected into the WorkOS sign-in flow.

Reusable frontend components live in `apps/web/src/components` so they can move into `packages/ui` when shared UI conventions are established.

## Backend Setup

The backend lives in `apps/api` and uses FastAPI, Pydantic, Uvicorn, Ruff, Black, and Pytest.

Environment configuration is read from environment variables. Start from the safe template:

```sh
cp .env.example .env
```

For local API development, set:

```sh
APP_ENV=local
API_HOST=0.0.0.0
API_PORT=4000
ALLOWED_FRONTEND_ORIGINS=http://localhost:3000
```

Create a Python virtual environment and install the database package plus the API package:

```sh
cd apps/api
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ../../packages/database
python -m pip install -e ".[dev]"
```

Run the API from the repository root:

```sh
pnpm api:dev
```

Or run it directly from `apps/api`:

```sh
python scripts/dev.py
```

Core endpoints:

- `/` - API metadata.
- `/health` - health check.
- `/health/database` - database connectivity check.
- `/api/v1/status` - versioned API status.
- `/api/v1/me` - protected current user and organization memberships.
- `/api/v1/workspaces/{workspace_id}/profiles...` - workspace people and
  profile APIs.
- `/api/v1/workspaces/{workspace_id}/artist-profiles...` - artist profile APIs.
- `/api/v1/workspaces/{workspace_id}/campaigns...` - campaign records,
  lifecycle, relationships, members, goals, milestones, and planning APIs.
- `/api/v1/workspaces/{workspace_id}/marketing-content...` - marketing content
  list, create, update, archive, status, channel schedule, and publish APIs.
- `/api/v1/workspaces/{workspace_id}/approvals...` - Approval Queue list,
  detail, assignment, decision, and history APIs.
- `/api/v1/workspaces/{workspace_id}/campaign-calendar` - read-only Campaign
  Calendar projection API.
- `/api/v1/workspaces/{workspace_id}/analytics...` - analytics providers,
  metric definitions, observations, series, summary, comparison, and latest
  observation APIs.
- `/api/v1/workspaces/{workspace_id}/roles...` and member role APIs - workspace
  capability and role administration.
- `/api/v1/dashboard/summary` - organization-scoped dashboard summary with
  permission-filtered card and section availability.
- `/api/v1/dashboard/performance` - protected label performance series for
  authorized dashboard users.
- `/api/v1/realtime/organizations/{organization_id}/events` - organization
  realtime event stream used by the dashboard shell and recent activity.

Run backend validation from the repository root:

```sh
pnpm api:test
pnpm api:lint
pnpm api:format
```

## Database Setup

The database foundation lives in `packages/database` and uses PostgreSQL, SQLAlchemy 2 async access, Alembic, and Pydantic settings.

Start from the safe environment template and set local-only database credentials:

```sh
cp .env.example .env
```

The relevant local variables are:

```sh
POSTGRES_DB=labelos
POSTGRES_USER=labelos
POSTGRES_PASSWORD=replace-with-local-db-password
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://labelos:replace-with-local-db-password@localhost:5432/labelos
COMPOSE_DATABASE_URL=postgresql+asyncpg://labelos:replace-with-local-db-password@postgres:5432/labelos
DATABASE_ECHO=false
```

`DATABASE_URL` is used by host-run API and Alembic commands. `COMPOSE_DATABASE_URL` is used by the API container because the PostgreSQL hostname inside Compose is `postgres`.

Database commands from the repository root:

```sh
pnpm db:start
pnpm db:migrate
pnpm db:migration -- -m "describe change"
pnpm db:rollback
```

`pnpm db:start` uses the repository Compose wrapper, which prefers
`docker compose` and falls back to `docker-compose`. The wrapper also uses an
isolated temporary Docker config directory, avoiding local credential-store
permission warnings from user-level Docker config files.

The migration chain now covers these major model families:

- Identity and authentication: `users`, `auth_identities`, WorkOS webhook event
  tracking, organizations, and organization memberships.
- Universal profiles, artist profiles, profile metadata, preferences, and
  workspace memberships.
- Departments, roles, role capabilities, role assignments, capability
  permissions, and workspace invite roles.
- Campaign records, campaign members, campaign artist/release links, goals, and
  milestones.
- Analytics providers, metric definitions, observations, and idempotency
  fingerprints.
- Marketing content items, channels, content revisions, scheduled/published
  timestamps, and approval projection fields.
- Approval requests, approval request stages, and approval decisions.
- Realtime event storage.

`auth_identities` links an external provider subject to the local `users` table.
Organization memberships separate administrative workspace permission from
music-industry professional context. Workspace permissions are:

- `owner`
- `admin`
- `member`
- `guest`

The initial application authorization policy uses Owner, Admin, and Member with
WorkOS RBAC permission claims such as `artists:view` and `settings:manage`.
Backend FastAPI dependencies enforce permissions on protected routes; frontend
helpers only hide or disable unavailable actions. See
[Authorization](docs/development/authorization.md) for the initial
role-to-permission mapping and guard examples.

Do not commit real credentials. Keep personal values in `.env`; `.env.example` should remain a safe template.

## Implemented Product Domains

### Workspace Authorization

Label OS uses backend-enforced capability checks as the authoritative access
control layer. WorkOS session role and permission claims are compatibility
inputs, while local workspace memberships, departments, roles, and capability
grants determine effective access.

Frontend helpers hide unavailable navigation and controls, but FastAPI
dependencies and service-level authorization checks remain the enforcement
point. Workspace-scoped queries include the resolved local workspace ID and
avoid cross-workspace reads.

### Campaigns

Campaigns are workspace-scoped operational containers for artists, releases,
team members, goals, milestones, and downstream workflow attachments. The
canonical Campaign model owns:

- campaign name, description, type, status, owner, creator, start date, and
  target end date;
- campaign members linked to workspace memberships;
- artist and release relationships;
- lightweight campaign goals and milestones;
- realtime events for campaign lifecycle and relationship changes.

Campaign API operations use `marketing.campaign.*` capabilities. See
[Campaign Domain Contract](docs/development/campaign-domain-contract.md) for
the deeper model and integration boundaries.

### Marketing Hub

The Marketing Hub at `/marketing` is the content-specific operational surface.
It supports marketing content records, drafts, owner/creator context, schedule
and publish timestamps, channel-level schedule/publish times, content revision
tracking, archive/status updates, and approval submission entry points.

The Marketing Content Calendar remains distinct from Campaign Calendar:

- Marketing Content Calendar: content-specific operational scheduling and
  editing surface.
- Campaign Calendar: read-only cross-campaign projection/timeline.

### Approval Queue

Approval Queue is the owner of approval lifecycle state. Approval requests track
resource type, resource ID, resource revision, status, requester context, stage
assignment, submitted/resolved timestamps, decision history, and immutable
decision metadata.

Marketing content integrates with Approval Queue through canonical approval
requests and resource adapters. The system tracks whether an approved revision
is still current and whether content can be scheduled from the current canonical
approval state.

### Campaign Calendar

Campaign Calendar at `/campaign-calendar` is a read-only projection service. It
does not create a `calendar_events` table, does not own domain state, and does
not add a separate `marketing.calendar.view` capability. Access requires the
existing `marketing.campaign.view` and `marketing.content.view` capabilities.

The projection currently emits:

- `campaign.start`
- `campaign.target_end`
- `campaign.milestone.target`
- `marketing.content.scheduled`
- `marketing.content.channel_scheduled`
- `marketing.content.published`
- `marketing.content.channel_published`
- `marketing.content.approval_requested`
- `marketing.content.approved`

The projection intentionally does not emit release target events, campaign goal
target events, or approval deadline/SLA events until canonical date fields exist
for those domains.

### Analytics

Analytics Objects provide workspace-scoped providers, metric definitions,
observations, latest-value lookups, series, comparisons, and dashboard summary
data. Campaign-level observations can attach to campaign IDs, and child
campaign observations use typed campaign object references.

### Realtime

Realtime events are organization/workspace-scoped and feed recent activity,
local cache invalidation, and page refresh behavior. Campaign, marketing
content, approval, profile/artist, release, analytics, member, and role changes
invalidate only the relevant workspace-scoped frontend caches where possible.

## Agent Service Setup

The agent service lives in `apps/agents` and uses FastAPI, Pydantic, Uvicorn,
Ruff, Black, and Pytest. It currently includes deterministic placeholder agents
only; it does not call external AI APIs.

Create a Python virtual environment and install the package:

```sh
cd apps/agents
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
```

Relevant local variables:

```sh
AGENTS_HOST=0.0.0.0
AGENTS_PORT=4100
AGENTS_LOG_LEVEL=INFO
AGENTS_MODEL_PROVIDER=mock
AGENTS_MODEL_NAME=mock-deterministic
AGENTS_MODEL_TIMEOUT_SECONDS=30
AGENTS_REQUIRE_HUMAN_APPROVAL=true
```

Future provider credentials should stay in local environment variables such as
`AGENTS_OPENAI_API_KEY`, `AGENTS_ANTHROPIC_API_KEY`, or
`AGENTS_GOOGLE_API_KEY`. Do not commit real API keys.

Run validation from the repository root:

```sh
pnpm agents:test
pnpm agents:lint
pnpm agents:health
```

Starter endpoints:

- `/` - agent service metadata.
- `/health` - health check.
- `/api/v1/status` - versioned agent service status.

The agent package separates agent definitions, tools, workflows, memory,
evaluation, and provider integrations under `apps/agents/src/labelos_agents`.
See `apps/agents/README.md` for the shared contracts and new-agent checklist.

## Authentication Setup

Authentication is implemented with WorkOS AuthKit:

1. The browser opens `/api/auth/login`.
2. The Next.js server route redirects to the WorkOS-hosted AuthKit sign-in flow.
3. WorkOS redirects back to `/api/auth/callback`.
4. The AuthKit Next.js SDK stores and refreshes the encrypted app session.
5. Server-side Next.js code obtains the WorkOS access token with AuthKit helpers
   and forwards it to FastAPI as a bearer token for protected API calls.
6. FastAPI verifies the WorkOS JWT against the WorkOS JWKS on every protected
   request.
7. The API resolves WorkOS user and organization IDs to local `User`,
   `AuthIdentity`, `Organization`, and `OrganizationMembership` records.

### WorkOS Dashboard Setup

In the WorkOS dashboard:

1. Create or select the Label OS environment.
2. Enable AuthKit and copy the Client ID and API Key into local or production
   secret storage.
3. Configure RBAC roles with these initial slugs: `owner`, `admin`, `member`,
   `artist`, `viewer`, and `guest`.
4. Configure permission/capability slugs to match the application authorization
   model documented in [Authorization](docs/development/authorization.md),
   including workspace, profile, artist, release, marketing campaign, marketing
   content, contract, royalty, finance, and analytics capabilities.
5. Configure the webhook endpoint and copy the signing secret into
   `WORKOS_WEBHOOK_SECRET`.

Required local redirect URI:

```text
http://localhost:3000/api/auth/callback
```

Required production redirect URI:

```text
https://<your-web-domain>/api/auth/callback
```

Required auth environment variables:

```sh
AUTH_PROVIDER=workos
WORKOS_CLIENT_ID=client_replace_with_workos_client_id
WORKOS_API_KEY=sk_replace_with_workos_api_key
WORKOS_COOKIE_PASSWORD=replace-with-at-least-32-characters
WORKOS_REDIRECT_URI=http://localhost:3000/api/auth/callback
NEXT_PUBLIC_WORKOS_REDIRECT_URI=http://localhost:3000/api/auth/callback
WORKOS_ISSUER_URL=https://api.workos.com
WORKOS_JWKS_URL=
WORKOS_WEBHOOK_SECRET=whsec_replace_when_webhooks_are_enabled
```

`WORKOS_API_KEY`, `WORKOS_COOKIE_PASSWORD`, `WORKOS_WEBHOOK_SECRET`, database
passwords, and WorkOS access tokens must never be exposed through
`NEXT_PUBLIC_*` variables. External WorkOS credentials are not included in this
repository, so the live AuthKit redirect and token exchange cannot be verified
locally until those values are supplied. The local API tests verify the token
validation structure with signed WorkOS-shaped test JWTs and a mocked JWKS
client. See [WorkOS Environment Setup](docs/development/workos-environment.md)
for the full local, test, and production environment structure.

### Authentication Local Startup

Use the root `.env.example` as the local template, fill in WorkOS values from
the dashboard, then start the stack:

```sh
pnpm install
pnpm db:start
pnpm db:migrate
pnpm api:dev
pnpm dev
```

The local AuthKit sign-in entrypoint is:

```text
http://localhost:3000/api/auth/login
```

### Authentication Test Commands

Run the authentication validation commands from the repository root:

```sh
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test
pnpm api:lint
pnpm build
pnpm compose -- build api
```

`pnpm test` covers frontend AuthKit routes, protected-route behavior,
access-token forwarding and refresh, FastAPI JWT validation, the current-user
endpoint, organization onboarding, role and permission enforcement,
cross-organization isolation, and WorkOS webhook verification. The Docker build
requires a running Docker daemon.

### Authentication Security Model

AuthKit owns the browser session cookie. Label OS does not set authentication
cookies directly; production deployments must use `NODE_ENV=production`, HTTPS
`WEB_BASE_URL` and `WORKOS_REDIRECT_URI` values, and a generated
`WORKOS_COOKIE_PASSWORD` of at least 32 characters.

The Next.js server is the only frontend layer that reads the WorkOS access
token. It forwards the token to FastAPI as a bearer token and retries once after
an unauthorized response by refreshing the AuthKit session. Raw token values are
not returned to React components or API responses.

FastAPI validates WorkOS JWTs with RS256, the configured issuer, required
`exp`, `iss`, `sub`, and `sid` claims, and the WorkOS JWKS URL. When
`WORKOS_AUDIENCE` is configured, audience validation is enabled.

Redirects from login and logout are constrained to same-origin application paths
and reject control characters and backslashes, preventing open redirects. CORS
uses the explicit `ALLOWED_FRONTEND_ORIGINS` allowlist. Error responses use
generic authentication, authorization, validation, webhook, and internal-error
messages and do not include raw tokens or provider secrets.

### Role, Capability, Permission, And Organization Model

WorkOS is the source of session role and permission claims. Local Label OS
workspace memberships, role assignments, department grants, and capability rows
are the source of application authorization. FastAPI route dependencies and
service checks are the enforcement point:

- Missing or invalid bearer token: `401`.
- Authenticated user without an active organization: `403`.
- Authenticated user without the required role or permission: `403`.
- Organization-scoped data queries always include the active local organization
  ID resolved from the WorkOS `org_id` claim.

The initial workspace permission hierarchy is `owner` > `admin` > `member` >
`guest`, with `artist` and `viewer` mapped into constrained workspace access.
Frontend helpers only hide or disable unavailable actions.

### WorkOS Webhooks

Configure WorkOS to send webhook events to:

```text
https://<your-api-domain>/api/v1/webhooks/workos
```

The API verifies the `workos-signature` header with the configured
`WORKOS_WEBHOOK_SECRET`, enforces a five-minute timestamp tolerance, records
processed event IDs for idempotency, ignores unsupported event types, and skips
older out-of-order events for the same resource. Supported events synchronize
users, organizations, and organization memberships into local tables.

## Docker Local Development

Docker support is provided for the web, API, and PostgreSQL services.

### Docker Prerequisites

- Docker Desktop or Docker Engine with Docker Compose.
- Ports `3000`, `4000`, and `5432` available on the host, unless overridden.
- Optional root `.env` file copied from `.env.example`.

The compose stack uses environment variables instead of hardcoded secrets. The
current Docker setup requires:

```sh
APP_ENV=local
API_PORT=4000
WEB_PORT=3000
NEXT_PUBLIC_API_URL=http://localhost:4000
NEXT_PUBLIC_WORKOS_REDIRECT_URI=http://localhost:3000/api/auth/callback
API_BASE_URL=http://api:4000
ALLOWED_FRONTEND_ORIGINS=http://localhost:3000
LOG_LEVEL=INFO
POSTGRES_DB=labelos
POSTGRES_USER=labelos
POSTGRES_PASSWORD=replace-with-local-db-password
DATABASE_URL=postgresql+asyncpg://labelos:replace-with-local-db-password@localhost:5432/labelos
COMPOSE_DATABASE_URL=postgresql+asyncpg://labelos:replace-with-local-db-password@postgres:5432/labelos
AUTH_PROVIDER=workos
WORKOS_CLIENT_ID=client_replace_with_workos_client_id
WORKOS_API_KEY=sk_replace_with_workos_api_key
WORKOS_COOKIE_PASSWORD=replace-with-at-least-32-characters
WORKOS_REDIRECT_URI=http://localhost:3000/api/auth/callback
NEXT_PUBLIC_WORKOS_REDIRECT_URI=http://localhost:3000/api/auth/callback
WORKOS_ISSUER_URL=https://api.workos.com
WORKOS_WEBHOOK_SECRET=whsec_replace_when_webhooks_are_enabled
```

`NEXT_PUBLIC_API_URL` is passed as a web image build argument because public
Next.js environment variables are embedded into the browser bundle at build
time. Use `API_BASE_URL=http://api:4000` for server-side calls between
containers.

### Build Commands

Build both images:

```sh
pnpm compose -- build
```

The `pnpm compose -- ...` wrapper prefers Compose v2 and falls back to the
legacy `docker-compose` binary when Compose v2 is not installed.

Build a single service:

```sh
pnpm compose -- build web
pnpm compose -- build api
pnpm compose -- pull postgres
```

### Startup Commands

Start the stack:

```sh
pnpm compose -- up
```

Start in the background:

```sh
pnpm compose -- up -d
```

Start PostgreSQL only:

```sh
pnpm db:start
```

The services are available at:

- Web: `http://localhost:3000`
- Web health: `http://localhost:3000/api/health`
- API: `http://localhost:4000`
- API health: `http://localhost:4000/health`
- API database health: `http://localhost:4000/health/database`
- PostgreSQL: `localhost:5432`

### Shutdown Commands

Stop the stack:

```sh
pnpm compose -- down
```

Stop and remove built images created by compose:

```sh
pnpm compose -- down --rmi local
```

### Docker Troubleshooting

- If a port is already in use, set `WEB_PORT` or `API_PORT` in `.env`, then run
  `pnpm compose -- up --build`.
- If frontend API configuration appears stale, rebuild the web image because
  `NEXT_PUBLIC_API_URL` is embedded during `next build`.
- If CORS requests fail from the browser, make sure
  `ALLOWED_FRONTEND_ORIGINS` includes the exact web origin, such as
  `http://localhost:3000`.
- If health checks fail, inspect logs with `pnpm compose -- logs web api`.
- If dependency installs seem stale, rebuild without cache:
  `pnpm compose -- build --no-cache`.

## Contributing

1. Create a branch from the default branch.
2. Keep changes focused and scoped to one concern.
3. Add or update tests and documentation when behavior changes.
4. Run the relevant validation commands before opening a pull request.
5. Open a pull request using the template and describe the validation performed.

No secrets should be committed. Use `.env.example` as the safe template for local configuration.
