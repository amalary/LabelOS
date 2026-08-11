# Development Seed Data

LabelOS includes a guarded development seed for a fake organization workspace.
It is intended for local development only and is never run automatically by
migrations, startup, or tests.

## Seed Command

Start the local database, apply migrations, then run:

```bash
pnpm db:start
pnpm db:migrate
APP_ENV=local pnpm db:seed:dev
```

On Windows PowerShell:

```powershell
$env:APP_ENV = "local"
pnpm db:seed:dev
```

## Seed Records

The seed creates the `Malary Records` development organization with clearly fake
WorkOS identifiers and `example.test` email identities:

- Owner: `Mara Vale (Dev Owner)` / `owner+dev-seed@malary-records.example.test`
- Admin: `Inez Park (Dev Admin)` / `admin+dev-seed@malary-records.example.test`
- Member: `Theo King (Dev Member)` / `member+dev-seed@malary-records.example.test`
- Artists: `Nia Calder`, `The Harbor Lights`, `Juniper Knox`, `Vega North`,
  `Milo Reyes`

## Environment Protection

The seed refuses to run unless `APP_ENV` is one of `local`, `development`,
`dev`, or `test`.

It also refuses remote database URLs. The database URL must be SQLite or a local
PostgreSQL URL containing `localhost`, `127.0.0.1`, or `::1`.

## Idempotency

The seed is repeatable. It looks up deterministic development WorkOS IDs,
organization slug, organization memberships, and organization-scoped artist
names before inserting. Re-running the command updates the seeded records in
place and avoids duplicate users, memberships, organizations, and artists.
