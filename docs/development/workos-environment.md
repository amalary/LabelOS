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
the WorkOS SDK on the Next.js server.

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
