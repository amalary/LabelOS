# Scheduling transaction foundation

Implemented against the accepted [Scheduling Engine contract](scheduling-engine-contract.md),
[stable channel identity](marketing-channel-reconciliation.md),
[timezone authoring](timezone-safe-scheduling.md), and
[shared eligibility](scheduling-eligibility.md) foundations.

The subsequent [persistence implementation](scheduling-persistence.md) adds job and
history storage with restricted deletion. The
[production-readiness audit](scheduling-production-readiness.md) completes material-edit
invalidation: occupying sibling jobs retire in the content transaction, including
claimed jobs, while terminal history remains unchanged. The phase-specific
verification notes below record the earlier foundation work.

## Boundaries and audit

| Area                        | Audit finding and resulting boundary                                                                                                                                                                                                                                |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Marketing Content           | Create, edit, combined edit, replacement, single-channel edit, status transition and archive committed internally. Each now has a private, flush-only operation body. Existing public functions own one final commit.                                               |
| Nested approval transitions | Content submission/approval now calls the noncommitting approval bodies. The content application boundary commits the whole operation.                                                                                                                              |
| Approval                    | Submission, assignment, human decisions, cancellation/invalidation and resubmission now have noncommitting bodies. Resubmission no longer commits its new submission before adding resubmission history and realtime.                                               |
| Repositories                | Content and approval writes already flushed without committing. This remains true. Approval resource adapters also never commit.                                                                                                                                    |
| Realtime                    | `RealtimePublisher.publish` inserts and flushes the database outbox record in the supplied session. No network dispatch or independent commit was added.                                                                                                            |
| Invalidation                | `record_current_approval_invalidated` and `invalidate_content_channels` remain transaction-local. The hook supersedes active sibling jobs, fences claims, and writes audit/outbox records before mutation. Referenced physical deletion still fails and rolls back. |
| Destination resolution      | The existing resolver performs reads without committing. It remains an authoring/read projection boundary; it is not an authenticated worker adapter.                                                                                                               |

Public service signatures, authoring permissions, endpoint payloads and planning
status semantics remain compatible. Public write wrappers use a savepoint for the
operation, then commit once. A domain validation error rolls back that savepoint
without expiring unrelated loaded caller objects. Unexpected exceptions also roll
back the outer transaction. This preserves existing validation-call behavior while
preventing partial operation writes, including a failure during resubmission.

The existing public functions still accept their legacy optional actor argument.
That compatibility is not available through the new composition boundary and must
never be used as a worker credential.

## Composition interface

`services/content_transactions.py` exposes `MarketingContentTransaction` and
`ApprovalTransaction`. Both require an explicit non-null authoring actor, retain
existing capability/resource checks, and use the supplied session. They do not
begin, commit or roll back transactions. Their caller owns the complete unit of
work and must roll back on any failure, including domain errors. Do not mix these
operations with a committing public service inside a composed transaction.

```python
async with session_factory.begin() as session:
    content = MarketingContentTransaction(session, workspace_id, actor=actor)
    source = await content.verify_scheduling_source(
        content_item_id,
        channel_id,
        expected_content_revision=expected_revision,
        expected_schedule_generation=expected_generation,
    )
    # Future scheduling application code performs active-slot/idempotency checks,
    # job/history writes and realtime insertion here, using this same session.
# The outer application context commits once, or rolls everything back on error.
```

The source verifier locks and reloads the workspace-owned parent and its channels,
checks the selected channel belongs to that parent, compares expected revision and
generation, and loads authoritative approval evidence under locks. It requires a
current approved revision, the authoritative completed request without an
invalidation decision, a noncontradictory request pointer, an approved/scheduled
parent, and valid channel time plus timezone/local/offset context.

`LockedSchedulingSource` contains transaction-local source records and approval
evidence. It is not a durable snapshot, full scheduling eligibility or activation
authority. Its view permission only permits source inspection. Future activation
must still enforce the dedicated scheduling capability, scope/control checks,
lateness, destination/effective-artist verification, active-slot uniqueness,
idempotency and snapshot construction. Never reuse its records after the outer
transaction ends or after a source mutation in the same transaction.

## Locking

Content writers retain the parent-first lock and now explicitly lock and refresh
channels in ID order. Approval writers lock the parent/channels before the request
and its stages; stages are locked/refreshed in ID order. Locked approval evidence
locks candidate requests in ID order before selecting the same authority used by
the read projection. The parent lock serializes compliant approval insertions and
invalidation decisions, including when no approval request exists yet.

Human decisions retain conditional request/stage transitions, using returned row
IDs to detect a lost state guard. Resubmission reloads its prior request under the
same parent-first protocol. A stale ORM identity map is not used as authoritative
state after waiting for a lock. Multi-parent future operations must acquire all
parents in ID order before acquiring their descendants, as specified by the
contract. Campaign/artist context, execution-control, job and destination locks
remain part of those future operations.

## Verification

`test_content_transactions.py` compares parent, channel, approval request, stage,
decision and realtime tables before and after rollback for all operation families.
It forbids nested commits, exercises channel deletion and the existing invalidation
hook, tests a failure after submission during public resubmission, and verifies
that PostgreSQL observers see neither content nor realtime before outer commit.
PostgreSQL race tests observe actual server lock waits and prove that material
edits and approval decisions cannot authorize a stale revision. Existing PostgreSQL
reconciliation/race tests also remain in the regression set.

The existing approval double-decision test now runs sequentially on in-memory
SQLite, whose StaticPool supplies one shared physical connection and cannot model
independent concurrent savepoints. Its PostgreSQL parameter retains the real
concurrent race. SQLite is not evidence for row-lock correctness.

Broad regression: **613 passed**, covering PostgreSQL, services, APIs, approvals,
realtime, calendars, social accounts and database foundations. The migration test
emitted eight existing Alembic Windows asyncio-policy deprecation warnings.

Final focused validation: **69 passed** on SQLite and PostgreSQL. The added
partial-guard rollback test passed on both databases (**2 passed**); a final
contradictory-pointer/guard rerun passed **4 tests**. These runs overlap.
Repository and targeted Pyright, API Ruff, Black formatting of all seven changed
Python files, Markdown Prettier and `git diff --check` passed.

Run from `apps/api`, with `TEST_POSTGRES_URL` configured for local PostgreSQL.
Tests create and clean up isolated schemas; no application migration was applied.

```powershell
python -m pytest tests/test_content_transactions.py tests/test_scheduling_eligibility.py tests/test_scheduling_contracts.py tests/test_schedule_timezones.py tests/test_marketing_content_repository.py tests/test_marketing_content_service.py tests/test_marketing_content_api.py tests/test_marketing_content_postgres.py tests/test_approval_repository.py tests/test_approval_service.py tests/test_realtime.py tests/test_campaign_calendar_repository.py tests/test_campaign_calendar_service.py tests/test_campaign_calendar_api.py tests/test_social_account_service.py tests/test_social_account_connections_api.py tests/test_database_foundation.py -q --tb=short --show-capture=no
python -m pytest tests/test_content_transactions.py tests/test_approval_service.py -q --tb=short --show-capture=no
python -m pytest tests/test_content_transactions.py -k 'pointer or guard_conflict' -q --tb=short --show-capture=no
python -m ruff check .
```

From the repository root:

```powershell
pnpm.cmd exec pyright
pnpm.cmd exec pyright apps/api/src/labelos_api/services/content_transactions.py apps/api/src/labelos_api/services/marketing_content_service.py apps/api/src/labelos_api/services/approval_service.py apps/api/src/labelos_api/repositories/marketing_content.py apps/api/src/labelos_api/repositories/approvals.py apps/api/src/labelos_api/services/content_invalidation.py apps/api/src/labelos_api/realtime
pnpm.cmd exec prettier --check docs/development/scheduling-transactions.md
git diff --check
```

Black was verified using `black.format_str`, line length 88 and Python 3.12 target,
matching the repository configuration. The final source audit found transaction
completion only in the 15 public application wrappers, with none in the scoped
operations, repositories, invalidation hook or realtime publisher.

## Deferred work

No scheduling-job table, migration, worker, workload identity, execution flags,
Delivery inbox or provider integration was added. The invalidation hook remains
inactive. Physical channel deletion remains the pre-job foundation behavior;
tombstones/restricted deletion and job cancellation/supersession/history must be
implemented together at the persistence gate. Existing Social Account resolver
`actor=None` compatibility must not be used to authenticate future execution;
that requires the separate trusted workload adapter specified by the contract.
