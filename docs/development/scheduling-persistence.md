# Scheduling Engine persistence

Implemented against the accepted [contract](scheduling-engine-contract.md), after
reading the completed [channel identity](marketing-channel-reconciliation.md),
[timezone authoring](timezone-safe-scheduling.md),
[shared eligibility](scheduling-eligibility.md), and
[transaction](scheduling-transactions.md) foundations.

## Migration and ownership

The actual Alembic head was checked twice before creating the revision:
`202609151000`. The single successor is `202609151800`.

`SchedulingJob` / `scheduling_jobs` stores one workspace-owned channel snapshot.
`workspace_id` references the existing `organizations` workspace table. Composite
restricted foreign keys enforce parent/workspace, channel/parent, destination/
workspace, and exact approval request/workspace/resource type/content ID/revision
bindings. Approval completion, invalidation decisions, current authority, artist
scope and eligibility still require the locked application checks; a foreign key
alone is not approval authorization.

The table includes all requested snapshot, claim, handoff, blocked, cancellation,
lineage and audit fields. The additional `activation_operation_id`,
`effective_artist_id`, `lineage_root_job_id`, `transition_version` and fixed
`approval_resource_type` retain the approved operation, context, lineage and
authorization concepts. A root job has null predecessor/root references; a
successor stores its predecessor and original root. Lineage references stay in
the same workspace and content item, allowing replacement channels with new IDs.
`handoff_receipt_id` is an opaque UUID, with no Delivery foreign key or table.

`SchedulingJobTransition` / `scheduling_job_transitions` provides append-only
operation, state, actor, reason and version history scoped to the job. Future
commands must insert these records in the same transaction as their job changes.
The database does not synthesize actors or infer transition history from updates.

## Intent and snapshots

Channel `scheduled_at` remains canonical. Job `scheduled_for` is its controlled
activation snapshot. Parent `scheduled_at` remains planning-only. No migration
scans historical schedules or inserts jobs, and no activation API or worker is
introduced.

The timezone foundation already supplies channel `schedule_generation`, starting
at 1 and incrementing once for material channel mutations through reconciliation
and single-channel updates. Those paths are retained. No-op edits, reordering and
publication-result changes preserve generation. Parent material revision changes
also fence unchanged sibling channels. Existing snapshot predicates detect changed
generation or instant; future execution must additionally check current revision,
approval, timezone, destination and context under the approved locks.

Database triggers reject updates to snapshot IDs, authorization, revision,
generation, time, timezone, destination, effective artist, idempotency/operation
keys, lineage, activation actor and creation time. They also reject every update
to cancelled, superseded or handed-off jobs, every job deletion, transition updates
or deletions, and decreasing fence/version counters. Blocking diagnostics may be
updated while nonterminal; terminal history remains immutable.

Scheduling instant types reject naive values at SQLAlchemy bind time, normalize
aware values to UTC, and return aware UTC values on both PostgreSQL and SQLite.
PostgreSQL uses `TIMESTAMP WITH TIME ZONE`; only persisted SQLite reads restore
its lost timezone information. The job model validates explicit IANA timezone
identifiers with `zoneinfo`, accepting `UTC` and rejecting bare abbreviations and
unknown zones. The database package explicitly depends on `tzdata` for Windows.

Blocked metadata accepts only `reason_codes` from the approved reason vocabulary
and nonnegative integer `observed_content_revision`, `observed_schedule_generation`
and `lateness_window_seconds`. Validation runs on assignment and SQLAlchemy bind,
including Core writes. It rejects arbitrary keys, free text, account/provider
payloads and credentials. This is an internal storage boundary, not a public DTO;
future commands must still sanitize cancellation and transition reason codes and
must not accept raw SQL or arbitrary metadata from callers.

## Constraints and indexes

All new foreign keys use `RESTRICT`. Constraints and indexes have stable names;
native PostgreSQL enums are explicitly created before tables and dropped after
tables on downgrade. SQLite uses the enum check constraints.

| Guard or index                                       | Purpose                                                                                                                                                                |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `uq_scheduling_jobs_active_channel`                  | Partial uniqueness for `pending`, `claimed`, **and `blocked`**.                                                                                                        |
| `uq_scheduling_jobs_activation_operation`            | One activation operation ID per workspace, retained across retries and terminal history.                                                                               |
| `uq_scheduling_jobs_idempotency_key`                 | Stable Delivery key uniqueness. The command layer constructs `labelos:scheduling:v1:{workspace_id}:{job_id}` and checks replay inputs.                                 |
| `uq_scheduling_jobs_handed_off_intent`               | Active jobs reserve channel/revision/generation; handed-off jobs retain that reservation permanently, preventing reactivation of accepted intent.                      |
| `uq_scheduling_jobs_handoff_receipt`                 | A receipt cannot settle multiple jobs.                                                                                                                                 |
| Named state/detail checks                            | Positive revision/generation/version, nonnegative fence, complete bounded claims, blocked reason/time, cancellation reason/time, and handoff receipt/time/destination. |
| `ix_scheduling_jobs_due`                             | Partial pending index on `(scheduled_for, id)` for ordered candidate selection.                                                                                        |
| `ix_scheduling_jobs_expired_claim`                   | Partial claimed index on `(claim_expires_at, id)` for recovery candidates.                                                                                             |
| Workspace list/status/due indexes                    | Workspace history pagination and filtered schedule lists.                                                                                                              |
| Channel history/content/approval/destination indexes | History lookup, invalidation candidates and reference checks.                                                                                                          |

Candidate selection does not lock a job before its parent. Future commands and
workers must follow the approved parent-first lock order and revalidate before
claims or acceptance. Counter monotonicity and row constraints do not replace
conditional state/version/fence writes, lease ownership checks, the lifecycle
graph, or transaction-local history/realtime insertion.

## Initial retention and deletion policy

**Retain every job and transition indefinitely in the initial release.** This
includes cancelled, blocked, superseded and handed-off history, activation
identity, original approval bindings and complete lineage. There is no TTL,
cleanup worker, scheduled deletion or automatic archival.

The initial physical retention design is restricted deletion. Existing source
deletion can continue for channels with no job references. Once referenced by any
job, a channel, content item, approval, destination, activation user or lineage
record cannot be deleted through a cascading operation. The database rejects the
operation and its owning transaction rolls back. Referenced channel removal or
logical replacement therefore cannot complete through the existing physical-delete
path; it must gain retirement/tombstone handling alongside cancellation,
supersession and history writes before an activation API is enabled.

Material edits to retained channels remain possible and make existing snapshots
detectably stale. The existing invalidation hook is still inactive. Wiring atomic
job invalidation, lifecycle cancellation and revocation blocking is part of the
next application-service gate; this storage change does not claim those operations
already cancel or supersede jobs. Execution remains unavailable.

A later retention or erasure policy requires a reviewed migration/operational
procedure preserving required audit evidence and lineage. Ordinary application
deletion cannot bypass the history guards. An explicit **schema downgrade drops
the two new tables and their history**; export/backup that history before rolling
back a populated deployment. Downgrade retains channel generations, authoring
context, schedule instants and publication results. Re-upgrade starts with empty
job/history tables and does not reactivate legacy intent.

## Validation

`test_scheduling_persistence.py` covers PostgreSQL and SQLite metadata creation,
scoped foreign keys, active/blocked/claimed uniqueness, operation/key uniqueness,
state checks, snapshot immutability, restricted deletion, terminal lineage,
append-only audit, UTC round trips, naive input, safe metadata and unchanged
publication fields. It proves channel edits advance generation while retaining the
job's old snapshot. PostgreSQL additionally tests competing activation inserts
and the due query's index plan.

Migration validation runs the complete prior migration chain on PostgreSQL,
then upgrades, downgrades and re-upgrades the new revision with seeded legacy
channel data. SQLite builds the prior model shape and tests this revision's full
round trip; older migrations contain PostgreSQL-only `ALTER TYPE` statements, so
full historical SQLite migration support is not claimed. Checks include a single
Alembic head, enum lifecycle, timestamp type, named indexes/checks/foreign keys,
no implicit jobs, unchanged legacy data and migrated-table constraint/trigger
behavior. PostgreSQL uses isolated schemas with automatic test cleanup; no
application database is migrated.

Verified on 2026-09-15:

- Foundation, timezone, contract, repository and persistence run: **288 passed**.
- Persistence rerun with the stronger handed-off intent reservation: **71 passed**.
- Final foreign-destination and mutated-metadata checks: **4 passed**.
- Transaction, Marketing service/API/PostgreSQL concurrency, eligibility,
  approval service and calendar service/API regression: **321 passed**.
- API/database Ruff, repository and targeted Pyright, Black formatting, Markdown
  Prettier, final single-head check and `git diff --check`: passed.

Counts overlap between runs. The timezone migration test emitted eight existing
Windows asyncio-policy deprecation warnings.

From `apps/api`, with `TEST_POSTGRES_URL` configured for local PostgreSQL:

```powershell
python -m pytest tests/test_scheduling_persistence.py tests/test_schedule_timezones.py tests/test_database_foundation.py tests/test_scheduling_contracts.py tests/test_marketing_content_repository.py -q --tb=short --show-capture=no
python -m pytest tests/test_content_transactions.py tests/test_marketing_content_service.py tests/test_marketing_content_api.py tests/test_marketing_content_postgres.py tests/test_scheduling_eligibility.py tests/test_approval_service.py tests/test_campaign_calendar_service.py tests/test_campaign_calendar_api.py -q --tb=short --show-capture=no
```

From the repository root:

```powershell
python -m alembic -c packages/database/alembic.ini heads
python -m ruff check packages/database/src/labelos_database packages/database/alembic/versions/202609151800_scheduling_persistence.py apps/api/tests/test_scheduling_persistence.py
pnpm.cmd exec pyright packages/database/src/labelos_database/models.py packages/database/src/labelos_database/scheduling.py packages/database/src/labelos_database/scheduling_guards.py
pnpm.cmd exec prettier --check docs/development/scheduling-persistence.md
git diff --check
```
