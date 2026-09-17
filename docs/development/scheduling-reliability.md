# Scheduling reliability and rollout policy

Execution stays disabled by default. There is no certified production Delivery
receiver and no provider publishing implementation. The current worker can be
deployed disabled; passing these tests does not authorize execution enablement.

## Resolved operating defaults

| Control                      | Initial policy                                               | Rationale                                                                                                                                                      |
| ---------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Batch size                   | 25; configurable 1–1000                                      | Each invocation has separate recovery and claim budgets. Start small enough to finish within the sweep deadline.                                               |
| Lease                        | 120 seconds; configurable 1–3600                             | Covers the default 30-second sweep plus rollback and recovery margin. Startup requires lease duration greater than sweep timeout.                              |
| Lateness                     | 300 seconds; configurable 0–86400                            | Applies only to already activated jobs. Missed windows block; they never publish late. New activation requires a future instant.                               |
| Handoff availability         | 3 attempts: initial attempt plus at most 2 automatic retries | Only explicit `RetryableUnavailable` permits requeue. The third known nonacceptance blocks with `missing_durable_delivery_receiver`.                           |
| Sweep timeout                | 30 seconds                                                   | Cancels and awaits rollback; earlier committed jobs remain durable.                                                                                            |
| Invocation cadence           | Every minute in UTC; Scheduler retry count 0 initially       | The next sweep handles recovery. Duplicate invocations remain safe under database locks and inbox keys.                                                        |
| Job and transition retention | Indefinite in PostgreSQL                                     | Retain activation identity, snapshots, fences, receipts and lineage for replay protection and audit.                                                           |
| Archival or deletion         | Neither automatically                                        | No TTL, deletion job or archive mover. Database triggers reject history deletion. A future archival policy must retain online uniqueness and receipt readback. |

The availability budget comes from committed, workspace/job-scoped transition
history, not process memory or Scheduler headers. Rollback consumes no durable
budget. Lease recovery and replacement workers do not reset it. Staleness and
lateness take precedence over the availability block. There is no in-process
retry loop or provider retry policy. An authorized human may explicitly revalidate
a blocked job if it is still current, eligible and within its window; this permits
one fresh probe, whose unavailability blocks immediately once the prior budget is
spent. It does not grant another pair of automatic retries.

Unknown exceptions and ambiguous commits leave the claim for durable readback or
lease recovery. They are not known nonacceptance and do not consume this availability
budget. Lateness bounds their eligibility. Never reset fences or manufacture a new
activation/idempotency key to resolve uncertain acceptance.

The 1000-job setting is a hard bound, not a throughput promise. Jobs are processed
sequentially after the claim transaction commits. Size batches using observed
transaction duration and backlog age; increasing the batch alone can cause later
claims to expire. Expired claims cannot accept Delivery, even if the receiver
returns success after expiry. Final conditional writes use database wall-clock time.

## Legacy activation safety

Migrations, startup, scheduled sweeps, reads and edits never create jobs for
existing planning rows. An enabled worker still ignores rows without explicit
Scheduling jobs. Activation requires an authenticated human with
`marketing.content.schedule`, workspace/campaign authorization, an operation UUID,
and current revision/generation guards. Both deployment eligibility and a certified
receiver are required. Controls are server inputs, not client-provided authority.

Every new activation rejects an instant at or before database wall-clock time,
including work inside the worker's five-minute lateness tolerance. It also rejects
unapproved/stale approval, missing or incompatible destinations, missing timezone
context, DST gaps and repeated local times without an explicit matching offset.
Operators must edit overdue or ambiguous intent and obtain any required fresh
approval before activating. Parent-only planning times are not executable intent.
An exact replay of a previously authorized operation returns its durable result;
it creates no new work, including when the original schedule is now overdue.

Physical channel removal remains restricted when history references that channel.
A racing removal waits for the parent lock and fails its foreign-key check; its
transaction must roll back. The original intent and claim remain intact. This is
not successful cancellation. Cancel the job explicitly before abandoning work;
even after cancellation, deleting the referenced channel requires a future
tombstone design that preserves historical references. Do not drop foreign keys
or purge history to make removal succeed.

## Emergency execution shutdown

In a trusted operator transaction, disable the reviewed workspace and **wait for
commit**:

```sql
BEGIN;
UPDATE scheduling_execution_controls
SET execution_enabled = false
WHERE workspace_id = '<reviewed-workspace-uuid>';
COMMIT;
```

A missing control row is already disabled. The update serializes with the shared
control lock held by claims and acceptance transactions. An acceptance committed
before the stop remains durable; subsequent transactions refuse execution. Then
pause Scheduler, set `SCHEDULING_EXECUTION_ENABLED=false` on worker revisions and
check traffic, or revoke the caller's Invoker permission. Neither pausing Scheduler
nor changing a deployment alone cancels an active transaction. Preserve controls,
leases, keys and receipts during rollback. See the full
[worker runbook](scheduling-worker.md#emergency-shutdown-and-rollback).

## Verification map

All concurrency and locking cases use separate PostgreSQL connections; SQLite is
not evidence for locking correctness. Test inbox implementations stay in tests.

| Risk                                                    | Regression coverage                                                                                                                              |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Simultaneous workers, duplicate Scheduler invocations   | Repository held-lock `SKIP LOCKED` tests; overlapping authenticated HTTP sweeps and receipt uniqueness                                           |
| Crash before handoff, expired lease, fencing            | Reliability crash test; processor recovery; every fenced repository transition; expiration during receiver acceptance                            |
| Crash after durable acceptance, duplicate handoff       | Processor lost-acknowledgement readback; concurrent inbox replay; one stable key, envelope and receipt                                           |
| Cancellation/edit/approval invalidation versus claim    | Reliability tests hold real locks in both orderings; blocked writers are observed via `pg_blocking_pids`; processor also revalidates after claim |
| Channel removal versus claim                            | Reliability foreign-key rollback test preserves source, claim and history                                                                        |
| Duplicate activation, stale revision/request/generation | Activation and repository races, explicit current evidence and source guards                                                                     |
| Destination changes, DST, missed windows                | Processor destination/profile refresh tests; timezone gap/fold cases; overdue and ambiguous legacy activation regressions                        |
| Large batches, query count                              | 61-job backlog drained in 25/25/11 batches; constant SELECT count for 1 versus 128 claim candidates                                              |
| Partial failure, rollback                               | Per-job processor failures; inbox/savepoint/outer rollback; availability retry evidence rolls back with the job                                  |
| Workspace isolation                                     | Repository/API scope tests; foreign claim rejection; backlog sweep leaves other workspace jobs untouched                                         |
| Sensitive logging                                       | Handoff structured JSON redaction and worker fixed-code responses; destination queries exclude credential columns                                |

Run from `apps/api` with `TEST_POSTGRES_URL` set to a disposable PostgreSQL database:

```powershell
python -m pytest tests -q -k 'scheduling or schedule_timezones or content_transactions or marketing_content_postgres'
```

The fixtures create and drop isolated random schemas. CI supplies PostgreSQL 16;
the focused local verification used PostgreSQL 17.5.

Validation on 2026-09-16: **637 passed**, including 21 new PostgreSQL reliability
cases, with no skipped selected tests. The eight warnings are Python 3.14
deprecations in the existing Windows migration event-loop setup. Scoped Ruff,
Black, Pyright, Markdown Prettier and `git diff --check` passed.

Embedded Alembic commands preserve existing application loggers. Migration
verification includes this guard so a migration run cannot silently suppress
scheduling outcomes, safe structured logs or batch metrics in the host process.
