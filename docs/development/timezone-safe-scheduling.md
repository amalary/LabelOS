# Timezone-safe scheduling authoring

Implemented against the accepted [Scheduling Engine contract](scheduling-engine-contract.md)
and [channel reconciliation foundation](marketing-channel-reconciliation.md).
This is authoring and validation only. No jobs, activation, workers, provider calls,
Delivery integration, or publication-result mutations are introduced.

## Canonical contract and persistence

Channel intent stores:

| Field                     | Meaning                                                                                                |
| ------------------------- | ------------------------------------------------------------------------------------------------------ |
| `scheduled_at`            | Canonical timezone-aware UTC instant.                                                                  |
| `schedule_timezone`       | Explicit IANA authoring zone, with `UTC` permitted.                                                    |
| `schedule_local_time`     | Entered local wall time, normalized as ISO text without an offset; preserves seconds and microseconds. |
| `schedule_offset_seconds` | Validated chosen UTC offset, including the occurrence selected during an overlap.                      |
| `schedule_generation`     | Server-owned counter starting at 1; increments once for each material channel mutation.                |

The three authoring-context columns are nullable. A missing authoring timezone
means legacy planning data, even when `scheduled_at` is a valid UTC instant.
Generation alone does not establish confirmed timezone intent or authorization.

Sections 2, 10, and 13 of the approved contract require the channel zone,
wall-time/offset audit context, and generation. These are dedicated columns so
ordinary content metadata replacement cannot silently overwrite that context.
The parent schedule remains separate planning data and gains no timezone column.
Future immutable job snapshots/history remain a separate implementation gate.

Alembic head was checked before editing: `202609061800`. The new linear revision is
`202609151000`. Upgrade adds only the four channel columns; existing timestamps
are untouched and timezone context is not inferred or backfilled. Downgrade drops
only the new columns, retaining existing schedule instants. Downgrade necessarily
discards newly authored context; re-upgrade leaves those schedules legacy until
explicitly confirmed again. Both database migration round trips were tested.

## API and backend validation

Channel create/replacement DTOs and the single-channel domain update accept
`schedule_timezone`, `schedule_local_time`, `schedule_disambiguation`
(`earlier` or `later`), and `schedule_offset_seconds`. The offset or occurrence
choice is required for ambiguous wall times. Both may be sent if they agree.
`scheduled_at` may be omitted for new explicit authoring; the server derives it.
If supplied, it must be aware and equal the derived instant. Example:

```json
{
  "channel": "instagram",
  "schedule_timezone": "America/New_York",
  "schedule_local_time": "2026-11-01T01:30",
  "schedule_disambiguation": "later",
  "scheduled_at": "2026-11-01T06:30:00Z"
}
```

The response includes the persisted zone, wall time, offset, generation, and UTC
instant. Disambiguation is represented durably by that instant and chosen offset.
An aware timestamp supplied alone remains accepted as legacy planning input.
Replacement retains its clearing-of-omitted-fields policy; a legacy client that
omits previously stored timezone context clears that context as a material edit.
Single-channel edits that omit all scheduling fields preserve scheduling context.

`scheduling/timezones.py` uses Python `zoneinfo`, never the server's local zone.
It tests both folds, converts each candidate to UTC, and round-trips it through the
zone. Only matching wall times survive. `tzdata` is declared explicitly so hosts
without a system IANA database, including Windows, have a fallback.

Domain errors expose `.code`. Scheduling API errors use HTTP 422 with the existing
string `detail` convention and an additive top-level `code`. Unrelated validation
errors keep their existing response shape. Stable codes are:

- `timezone_required`, `invalid_timezone`
- `local_time_required`, `invalid_local_time`
- `nonexistent_local_time`, `disambiguation_required`, `invalid_disambiguation`
- `timestamp_timezone_required`, `invalid_timestamp`, `timezone_instant_mismatch`

Bare abbreviations such as `PST` and `EST` are rejected even if installed in the
host timezone database. API and service authoring boundaries reject naive
instants. Only persisted UTC column readback handles SQLite's loss of `tzinfo`;
this exception is not used to reinterpret caller input.

## Frontend conversion and DST behavior

Marketing Hub uses `schedule-timezones.ts` and a narrowly scoped
`@js-temporal/polyfill` dependency. Existing dependencies had no authoring parser
that rejects DST gaps and requires an overlap choice; the calendar helper is a
display utility. Temporal avoids introducing a custom DST offset-search algorithm.

New channel rows show the workspace calendar zone as their initial editable
authoring zone. Existing confirmed rows use their stored authoring zone, independent
of the calendar display preference. Parent planning input uses its displayed zone.
Neither conversion slices timestamps nor parses wall time with browser-local
`new Date(value)`.

The form previews the entered local time, zone abbreviation, UTC offset, and exact
UTC instant. During an overlap it presents earlier/later choices with both offsets
and instants; editing the wall time or zone resets that choice. Gaps display an
error and cannot be submitted. Client and server validation failures preserve input.

New York `2026-03-08T02:30` is rejected. `2026-11-01T01:30` requires selection:
earlier is `05:30Z` (UTC-04:00), later is `06:30Z` (UTC-05:00). Tests also cover
Los Angeles transitions, UTC, Kathmandu's quarter-hour offset, Lord Howe's
half-hour overlap, normal future dates, and precise round trips.

## Legacy data and calendar compatibility

Legacy rows open with a blank authoring zone and a notice explaining which display
zone is used. An unchanged save sends the original instant without guessing a
zone. Changing that legacy time requires timezone confirmation. Confirming timezone
context is a material edit and requires fresh approval under the existing rules.
No process scans or activates historical timestamps.

Calendar implementation and event keys remain unchanged. Tests verify that a
Los Angeles-authored channel appears at the correct UTC/New York display time,
retains `marketing_content_channel:{id}:scheduled`, and leaves status, revision,
generation, and parent planning dates untouched. Existing campaign all-day dates
and display-timezone tests continue to pass. Calendar projections do not author
or activate scheduling work.

## Stable identity and approval

Schedule instant, timezone, wall-time context, and chosen offset are material
channel fields. Existing reconciliation retains identity and reports retained,
updated, created, and removed IDs as before. Generation advances for material
channel changes; unchanged siblings and publication-result edits do not advance it.
The service increments parent revision once for a logical edit, including combined
parent/channel changes. Existing stale-approved-revision bookkeeping is preserved.

Tests cover replacement, combined editing, and single-channel updates; they verify
the prior revision and approval ID reach the inactive invalidation hook before
mutation, and that approval history records invalidation. No-op saves preserve
approval, revision, identity, and generation.

## Files changed

- `apps/api/src/labelos_api/scheduling/timezones.py`: shared resolver and validation.
- `apps/api/src/labelos_api/services/marketing_content_service.py`: boundary validation.
- `apps/api/src/labelos_api/repositories/marketing_content.py`: material fields and generation.
- `apps/api/src/labelos_api/api/v1/marketing_content.py`: DTOs, response metadata, UTC readback.
- `apps/api/src/labelos_api/exceptions.py`: scheduling validation error codes.
- `packages/database/src/labelos_database/models.py`: channel authoring columns.
- `packages/database/alembic/versions/202609151000_channel_schedule_timezone.py`: additive migration.
- `apps/web/src/lib/schedule-timezones.ts`: Temporal authoring conversion.
- `apps/web/src/lib/marketing-content.ts`: channel types.
- `apps/web/src/app/marketing/marketing-workspace.tsx`: timezone and DST form controls.
- Backend tests: `test_schedule_timezones.py`, `test_marketing_content_api.py`,
  `test_marketing_content_service.py`, `test_marketing_content_repository.py`,
  `test_campaign_calendar_service.py`.
- Frontend tests: `schedule-timezones.test.ts`, `marketing-workspace.test.tsx`.
- Dependencies: `apps/api/pyproject.toml`, `apps/web/package.json`, `pnpm-lock.yaml`.
- This document and the link in `marketing-channel-reconciliation.md`.

## Verification

Results: the main backend regression run passed **327 tests**; the PostgreSQL
reconciliation/concurrency/rollback run passed **106 tests**. Follow-up schedule
edit and malformed/naive timestamp checks passed **24 tests** across SQLite and
PostgreSQL. Migration and reconciliation follow-ups passed **4 tests**, with the
new calendar projection check and **2** shared-error compatibility checks also
passing. Frontend marketing/calendar suites passed **131 tests**, including the
run under `TZ=Asia/Tokyo`; the final timezone utility run passed **14 tests**.
These runs overlap; the figures are per command, not a unique-test total.

Ruff, repository and targeted Pyright, TypeScript, ESLint, Prettier, Black
formatting for all 12 changed Python files, and `git diff --check` passed.

Commands below are run from `apps/api` unless otherwise noted. PostgreSQL tests
use `TEST_POSTGRES_URL` for the local database and isolated, automatically cleaned
schemas. No application database migration was applied.

```powershell
python -m alembic -c ../../packages/database/alembic.ini heads
python -m pytest tests/test_schedule_timezones.py tests/test_marketing_content_repository.py tests/test_marketing_content_service.py tests/test_marketing_content_api.py tests/test_campaign_calendar_service.py tests/test_campaign_calendar_repository.py tests/test_campaign_calendar_api.py tests/test_scheduling_contracts.py tests/test_database_foundation.py tests/test_approval_repository.py tests/test_approval_service.py -q --tb=short --show-capture=no
python -m pytest tests/test_marketing_content_postgres.py tests/test_marketing_content_service.py tests/test_marketing_content_api.py tests/test_marketing_content_repository.py -k 'postgresql or postgres' -q --tb=short --show-capture=no
python -m pytest tests/test_schedule_timezones.py tests/test_marketing_content_repository.py -k 'migration or timezone_reconciliation' -q --tb=short --show-capture=no
python -m pytest tests/test_campaign_calendar_service.py -k authoring_zone -q
python -m pytest tests/test_profiles_api.py -k 'rejects_workos_managed_identity_fields or validates_urls' -q
python -m pytest tests/test_marketing_content_service.py tests/test_marketing_content_api.py -k 'schedule_edits or naive_schedule' -q --tb=short --show-capture=no
python -m ruff check .
```

From `apps/web`, both the normal environment and `TZ=Asia/Tokyo` were used:

```powershell
pnpm.cmd exec vitest run src/lib/schedule-timezones.test.ts src/app/marketing/marketing-workspace.test.tsx src/lib/marketing-content.test.ts src/lib/calendar-dates.test.ts src/lib/campaign-calendar.test.ts src/app/campaign-calendar/campaign-calendar-workspace.test.tsx src/app/api/workspaces/campaign-calendar-proxy.test.ts
pnpm.cmd exec tsc --noEmit
pnpm.cmd exec eslint src/app/marketing/marketing-workspace.tsx src/app/marketing/marketing-workspace.test.tsx src/lib/marketing-content.ts src/lib/schedule-timezones.ts src/lib/schedule-timezones.test.ts
```

From the repository root:

```powershell
pnpm.cmd exec pyright
pnpm.cmd exec pyright apps/api/src/labelos_api/scheduling apps/api/src/labelos_api/repositories/marketing_content.py apps/api/src/labelos_api/services/marketing_content_service.py apps/api/src/labelos_api/api/v1/marketing_content.py apps/api/src/labelos_api/exceptions.py
python -m ruff check packages/database/src/labelos_database/models.py packages/database/alembic/versions/202609151000_channel_schedule_timezone.py
pnpm.cmd exec prettier --check apps/web/package.json pnpm-lock.yaml apps/web/src/lib/marketing-content.ts apps/web/src/lib/schedule-timezones.ts apps/web/src/lib/schedule-timezones.test.ts apps/web/src/app/marketing/marketing-workspace.tsx apps/web/src/app/marketing/marketing-workspace.test.tsx docs/development/timezone-safe-scheduling.md docs/development/marketing-channel-reconciliation.md
git diff --check
```

Python formatting is checked using Black's `format_str` API with line length 88
and Python 3.12 target. The migration test emits existing Alembic environment
deprecation warnings about Windows asyncio policies on Python 3.14.

## Remaining limitations

Browser and server timezone databases can differ. The server's round-trip and
instant/offset comparison rejects discrepancies instead of silently changing the
execution instant; the form retains input. Stored instants are not recomputed in
calendar reads or automatically moved after timezone database updates.

No contract conflicts identified. Future activation still needs the approved
authorization, transaction/locking, job/history, immutable snapshot, and Delivery
gates. A timezone-confirmed schedule is not itself executable or activated.
