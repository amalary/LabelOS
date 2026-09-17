# Marketing channel identity foundation

This implementation follows the accepted
[Scheduling Engine contract](scheduling-engine-contract.md). It adds no scheduling
jobs, APIs, worker, or publishing integration. Asset references retain their
existing authoring behavior; immutable delivery assets remain a separate gate.

## Identity and compatibility

Previously, channel replacement deleted all rows for a content item and inserted
the supplied collection again, changing IDs even on no-op saves. Reconciliation
now preserves rows with the same `(marketing_content_item_id, channel, placement)`.
Destination and list position are never identity inputs.

Replacement requests accept an optional channel `id`. The server validates it
against the authorized parent's existing channels. Unknown IDs, IDs from another
parent, stale IDs, and repeated claims to an ID are rejected. Legacy requests
without IDs match an unambiguous existing channel/placement pair. A change to
channel or placement removes the old logical channel and creates a new ID, also
when made through the single-channel service. The editor carries persisted IDs
through edits; new rows receive server-generated IDs. Response fields are unchanged.

## Reconciliation

1. Lock and reload the workspace-owned parent; retain existing authorization and
   destination validation.
2. Normalize service inputs and validate logical uniqueness and any supplied IDs.
3. Build a plan before changing rows: retained, created, updated, and removed.
4. For a material edit, record approval invalidation and invoke the transaction-local
   invalidation hook with the old revision, approval ID, all previous channel IDs,
   changed channel IDs, and explicitly removed IDs.
5. Apply updates, delete removed rows, flush released logical keys, insert new rows,
   and flush. The intermediate flush permits explicit-ID swaps without violating
   the existing database uniqueness constraint.
6. Insert the existing realtime event and commit at the owning service boundary.

The repository exposes `ChannelReconciliationResult` with retained, created,
updated, and removed IDs plus `material_change`. Updated IDs are a subset of
retained IDs. Result IDs and returned channel collections use deterministic
channel/placement ordering. IDs become durable only when the caller commits.

## Material changes and transactions

The [timezone-safe authoring foundation](timezone-safe-scheduling.md) adds explicit
channel timezone/wall-time/offset context and a server-owned generation counter.
Those scheduling edits are material and preserve the reconciliation rules below.

Channel copy, asset references, destination, scheduled time, metadata, channel,
placement, additions, and removals are material. A logical edit increments the
parent revision once, including combined parent/channel edits, and uses existing
approval invalidation and draft-reset behavior. No-op saves and reordering preserve
revision and approval. Publication result fields retain their nonmaterial policy.
Replacement retains its existing semantics of clearing omitted optional fields;
single-channel edits preserve unspecified fields.

Repository helpers and the invalidation hook never commit. The existing public
service remains the transaction owner. Single-channel and combined replacement
failures roll back source changes, revision, approval history, and realtime writes.
Future scheduling composition still requires the broader caller-owned service
unit-of-work refactor specified in the approved contract.

`services.content_invalidation.invalidate_content_channels` is an intentionally
inactive integration point, called under the parent lock before channel mutation
or deletion. Future implementation must cancel jobs on removed channels and
supersede other occupying jobs on the old parent revision, including unchanged
siblings, in the same transaction. It must not commit or dispatch external work.
This hook does not claim that any scheduling work has been cancelled today.

Physical channel deletion remains appropriate before durable job references
exist. Restricted deletion/tombstones and terminal history retention must be
implemented at the scheduling persistence gate; never cascade-delete job history.

## Verification commands

Verified on 2026-09-14: the combined backend run passed all **374 tests**, including
PostgreSQL concurrency and rollback tests, with no skips. The additional
foreign-ID API check passed on both databases (**2 passed**). The frontend
marketing tests passed **80 tests**. Ruff, both Pyright runs, TypeScript, ESLint,
Black formatting, Prettier, and `git diff --check` passed.

From `apps/api`, with `TEST_POSTGRES_URL` configured for local PostgreSQL (each
test uses an isolated, automatically cleaned schema):

```powershell
python -m pytest tests/test_marketing_content_repository.py tests/test_marketing_content_service.py tests/test_marketing_content_api.py tests/test_marketing_content_postgres.py tests/test_approval_repository.py tests/test_approval_service.py tests/test_database_foundation.py tests/test_scheduling_contracts.py -q
python -m pytest tests/test_marketing_content_api.py -k validates_explicit_ids -q
python -m ruff check .
```

From the repository root:

```powershell
pnpm.cmd exec pyright
pnpm.cmd exec pyright apps/api/src/labelos_api/repositories/marketing_content.py apps/api/src/labelos_api/services/marketing_content_service.py apps/api/src/labelos_api/services/content_invalidation.py apps/api/src/labelos_api/api/v1/marketing_content.py
pnpm.cmd exec prettier --check apps/web/src/app/marketing/marketing-workspace.tsx apps/web/src/app/marketing/marketing-workspace.test.tsx apps/web/src/lib/marketing-content.ts docs/development/marketing-channel-reconciliation.md
git diff --check
```

From `apps/web`:

```powershell
pnpm.cmd exec vitest run src/app/marketing/marketing-workspace.test.tsx src/lib/marketing-content.test.ts
pnpm.cmd exec tsc --noEmit
pnpm.cmd exec eslint src/app/marketing/marketing-workspace.tsx src/app/marketing/marketing-workspace.test.tsx src/lib/marketing-content.ts
```

The local Black CLI stalled after formatting and was stopped. Formatting was
subsequently checked successfully for all 108 API Python files using Black's
`format_str` API with line length 88 and Python 3.12 target, matching the repository
configuration. The API test file was checked again after adding foreign-workspace
ID coverage.
