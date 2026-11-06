# WorkOS Environment Setup

This project uses WorkOS AuthKit in the Next.js app and verifies WorkOS access
tokens in the FastAPI API. Start from `.env.example` for local development,
`.env.test.example` for test-only placeholders, and `.env.production.example`
for deployment shape. Do not commit real values.

## WorkOS Dashboard Values

Configure these URLs in the WorkOS dashboard for local development:

```text
Sign-in endpoint: http://localhost:3000/api/auth/login
Redirect URI: http://localhost:3000/api/auth/callback
Logout URI: http://localhost:3000/login
```

Use your deployed web origin for production. Do not invent production values in
the repository.

## Workspace creator role

The configured WorkOS environment must have an environment role with slug `owner`.
Workspace onboarding creates an owner membership, refreshes the organization
session, then synchronizes local records using that verified owner token. Do not
substitute `admin` or grant ownership based on organization names.

Onboarding checks for the role before creating an organization. On a retry it
can reuse an organization with matching LabelOS creator metadata and name only
when it is empty or the creator still has an active owner membership. It refuses
to reclaim an occupied workspace based on historical creator metadata alone.
Existing inactive or non-owner memberships are never upgraded by this path.

If creation previously failed because the role was missing, configure the role
in the intended WorkOS environment, refresh `/onboarding/workspace`, and submit
the same workspace name. Review leftover empty organizations separately; the
application does not delete them automatically.

## Server-Only Variables

These values must only be available to server runtimes or a secret manager:

```sh
WORKOS_API_KEY=sk_replace_with_workos_api_key
WORKOS_COOKIE_PASSWORD=replace-with-at-least-32-characters
WORKOS_WEBHOOK_SECRET=whsec_replace_when_webhooks_are_enabled
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<database>
COMPOSE_DATABASE_URL=postgresql+asyncpg://<user>:<password>@postgres:5432/<database>
POSTGRES_PASSWORD=replace-with-local-db-password
API_BASE_URL=http://localhost:4000
```

`WORKOS_API_KEY` must never use a `NEXT_PUBLIC_*` prefix. The API key is read by
the WorkOS SDK on the Next.js server and by the API's accepted-invitation
connection service. The API never returns the key to a client.

When an invited member first selects a workspace, the API verifies the active
local invitation membership, its inviter's current authority, and the member's
verified WorkOS identity. If the membership is not yet linked, it looks up all
WorkOS membership statuses and creates only an ordinary `member` membership when
none exists. Inactive/pending or privileged existing memberships require review;
this path does not reactivate, upgrade or downgrade them. Successful connection
stores the WorkOS membership ID and an audit event before AuthKit switches the
session. Linked memberships are never recreated by workspace activation.
The same path repairs an already accepted local invitation whose WorkOS link was
missing. It does not require a new invite or a new user account.

Leave `WORKOS_WEBHOOK_SECRET` empty locally until a real webhook signing secret
is configured. A documented example value is not a signing secret. With no real
value the local webhook endpoint deliberately returns 503; deployed environments
require the real value through strict startup validation.

Next development logging excludes authentication, invitation and OAuth routes.
The guarded API launcher uses structured request logs with route templates and
disables Uvicorn's duplicate access log, which otherwise records invitation tokens.
Do not enable full URL logging for these routes in external proxies or telemetry.

## Public Variables

These values may be exposed to browser code because they are URLs, not secrets:

```sh
NEXT_PUBLIC_API_URL=http://localhost:4000
NEXT_PUBLIC_WORKOS_REDIRECT_URI=http://localhost:3000/api/auth/callback
```

Changing a `NEXT_PUBLIC_*` value requires rebuilding the Next.js app because
Next.js embeds public variables during build.

## Backend WorkOS Verification

The backend validates WorkOS JWTs with:

```sh
AUTH_PROVIDER=workos
WORKOS_CLIENT_ID=client_replace_with_workos_client_id
WORKOS_ISSUER_URL=https://api.workos.com
WORKOS_JWKS_URL=
WORKOS_AUDIENCE=
```

Leave `WORKOS_JWKS_URL` empty unless you need an override. The API derives the
default JWKS URL as:

```text
https://api.workos.com/sso/jwks/<WORKOS_CLIENT_ID>
```

Leave `WORKOS_AUDIENCE` empty unless the WorkOS token shape for the configured
application requires audience validation.

## Cookie Password

Generate a strong AuthKit cookie password with:

```sh
openssl rand -base64 24
```

The resulting value is 32 characters and satisfies the WorkOS minimum. Store it
only in `.env`, deployment secrets, or your password manager.
