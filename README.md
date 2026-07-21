# Label OS

Label OS is an AI-powered operating system for record labels.

The product vision is to give labels one connected workspace for artist discovery, A&R workflows, release planning, marketing campaigns, analytics, royalties, contracts, AI agents, approval queues, and human-in-the-loop operations. The system should help teams move faster while keeping creative, financial, legal, and operational decisions reviewable by people.

## Project Status

This repository is in foundation setup. It contains the planned monorepo structure, documentation starters, repository hygiene files, a minimal Next.js frontend shell, a starter FastAPI backend, the initial PostgreSQL database foundation, authentication foundations, and a non-production AI agent service scaffold. Production agent workflows are intentionally not present yet.

## Prerequisites

- Node.js 24
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
  web/       Minimal Next.js frontend application.
  api/       Starter FastAPI backend service.
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
WEB_BASE_URL=http://localhost:3000
```

`NEXT_PUBLIC_API_URL` is intentionally public and must not contain secrets. Identity provider client secrets and token settings are read only by server-side route handlers and the API.

Run the frontend through the root workspace commands:

```sh
pnpm dev
pnpm build
pnpm lint
pnpm typecheck
```

The starter frontend currently provides:

- `/` - frontend starter placeholder.
- `/dashboard` - dashboard placeholder wrapped in the application shell.
- `/login` - starts the server-side SSO flow.

The `/dashboard` route is protected by Next middleware. Users without the
HttpOnly session token cookie are redirected to `/login`.

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

Starter endpoints:

- `/` - API metadata.
- `/health` - health check.
- `/health/database` - database connectivity check.
- `/api/v1/status` - versioned API status.
- `/api/v1/me` - protected current user and organization memberships.

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

The initial migration creates only foundational identity and organization tables:

- `users`
- `auth_identities`
- `organizations`
- `organization_memberships`

`auth_identities` links an external provider subject to the local `users` table.
Organization memberships support these roles:

- `owner`
- `admin`
- `member`
- `viewer`

Do not commit real credentials. Keep personal values in `.env`; `.env.example` should remain a safe template.

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

Authentication is implemented as a provider-agnostic OIDC-style authorization
code flow with PKCE:

1. The browser opens `/api/auth/login`.
2. The Next.js server route redirects to the configured identity provider.
3. The provider redirects back to `/api/auth/callback`.
4. The Next.js server route exchanges the code using `AUTH_CLIENT_SECRET`.
5. The access token is stored in an HttpOnly, SameSite=Lax cookie.
6. The API validates bearer tokens and resolves the external identity to a
   local `User` through `auth_identities`.

Required local callback URL:

```text
http://localhost:3000/api/auth/callback
```

Required production callback URL:

```text
https://<your-web-domain>/api/auth/callback
```

Required auth environment variables:

```sh
AUTH_PROVIDER=oidc
AUTH_ISSUER_URL=https://your-provider.example
AUTH_AUDIENCE=label-os-api
AUTH_JWT_ALGORITHMS=HS256
AUTH_TOKEN_SECRET=replace-with-api-token-validation-secret
AUTH_AUTHORIZATION_URL=https://your-provider.example/oauth2/v1/authorize
AUTH_TOKEN_URL=https://your-provider.example/oauth2/v1/token
AUTH_CLIENT_ID=replace-with-client-id
AUTH_CLIENT_SECRET=replace-with-client-secret
AUTH_CALLBACK_URL=http://localhost:3000/api/auth/callback
AUTH_SCOPE=openid email profile
```

`AUTH_CLIENT_SECRET` and `AUTH_TOKEN_SECRET` must never be exposed through
`NEXT_PUBLIC_*` variables. External provider credentials are not included in
this repository, so the live provider redirect and token exchange cannot be
verified locally until those values are supplied. The local API tests verify
the token validation structure with signed test JWTs.

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
API_BASE_URL=http://api:4000
ALLOWED_FRONTEND_ORIGINS=http://localhost:3000
LOG_LEVEL=INFO
POSTGRES_DB=labelos
POSTGRES_USER=labelos
POSTGRES_PASSWORD=replace-with-local-db-password
DATABASE_URL=postgresql+asyncpg://labelos:replace-with-local-db-password@localhost:5432/labelos
COMPOSE_DATABASE_URL=postgresql+asyncpg://labelos:replace-with-local-db-password@postgres:5432/labelos
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
