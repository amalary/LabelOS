# Scheduling Engine repository

`apps/api/src/labelos_api/repositories/scheduling.py` implements job persistence
over the existing scheduling tables and immutable snapshot/history guards.
Mutations require PostgreSQL and the default READ COMMITTED isolation level.

## Transaction and authorization boundary

Construct `SchedulingRepository(session, workspace_id,
lateness_window_seconds=...)` with an explicit workspace and nonnegative deployment
policy. Every operation, including worker batches and lease recovery, is workspace
scoped. Callers authenticate and authorize the human or workload identity before
using the repository. A worker must invoke it only for its allowlisted workspaces.

The repository flushes but never commits. The outer application owns one
transaction and must roll it back on failure. Job changes and append-only
transition records commit together. Do not call commit-owning legacy services
inside that transaction. No provider calls, queue dispatch, realtime events,
activation endpoints, polling loop, or execution enablement are introduced.

```python
async with session_factory.begin() as session:
    repository = SchedulingRepository(
        session, workspace_id, lateness_window_seconds=configured_window
    )
    jobs = await repository.claim_batch(
        worker_id=authenticated_worker.instance_id,
        limit=configured_batch_size,
        lease_duration=configured_lease_duration,
    )
    # Retain each job ID and fencing_token for subsequent transactions.
```

## Operations

| Method                      | Behavior                                                                                                                                                            |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `create_pending_job`        | Validates the supplied immutable activation against locked source rows, inserts pending work and activation history, or returns an exact replay.                    |
| `find_existing_job`         | Finds an activation operation in the workspace, including terminal history; rejects reuse with different snapshot, actor, destination, timezone, or lineage inputs. |
| `get_job`                   | Retrieves one workspace-owned job, or `None`.                                                                                                                       |
| `list_jobs`                 | Filters by status, parent, channel, and inclusive schedule range; uses descending `(created_at, id)` keyset pagination.                                             |
| `find_active_job`           | Returns the channel's pending, claimed, or blocked job.                                                                                                             |
| `cancel_pending_job`        | Cancels pending work with a fixed sanitized reason and advances the fence.                                                                                          |
| `supersede_active_job`      | Supersedes pending, claimed, or blocked work; claimed work requires the current unexpired lease. A successor activation validates predecessor/root lineage.         |
| `block_job`                 | Blocks pending or claimed work using the persisted reason allowlist; claimed work requires the current unexpired lease.                                             |
| `detect_stale_job`          | Retains locks and checks revision, authoritative approval, invalidation, parent state, destination/context, generation, instant, and timezone.                      |
| `find_due_pending_jobs`     | Reads bounded pending candidates, including missed work; does not reserve them.                                                                                     |
| `claim_batch`               | Claims at most the requested limit and blocks stale or missed candidates. Future work remains pending.                                                              |
| `recover_expired_leases`    | Privileged recovery of at most the limit of expired claims; requeues valid work or blocks stale/missed work, always advancing the fence.                            |
| `requeue_retryable_failure` | Requeues only an allowlisted internal failure under the current worker/fence/lease; blocks work that has become stale or late.                                      |
| `record_handoff_acceptance` | Verifies the request/receipt bindings and records acceptance under the current worker/fence/lease and lateness window.                                              |

All list/batch limits must be integers from 1 through 1000. Claims require a
positive configured lease duration. No default lateness window is supplied.

## Concurrency and stale work

Batch selection locks candidate parents in UUID order with
`SELECT FOR UPDATE SKIP LOCKED`, then locks campaigns, channels, approval requests,
and jobs in their respective UUID orders. Jobs also use `SKIP LOCKED`. Candidate
selection never locks a job before its parent. Parent locks serialize compliant
content and approval writers, including new requests and invalidation decisions.
Rows are refreshed after locks; stale SQLAlchemy identity-map values are not
authority. Approval evidence and source loading use a fixed number of queries per
batch; no per-job relationship reads are performed.

Each batch considers at most `limit` unlocked candidate parents and changes at most
`limit` jobs, selected by schedule and ID within those parents. It may return fewer
claims when locks, blocking decisions, or concurrent transitions consume candidates.
This is bounded polling, without a promise of strict global oldest-first fairness.
Run claim/recovery transactions promptly and commit before local preparation.

The database's partial unique indexes remain the final guard for the active channel
slot and accepted revision/generation intent. `INSERT ON CONFLICT DO NOTHING` plus
input-checked readback handles concurrent activation retries without poisoning the
outer transaction. A handed-off intent cannot be activated again under a new
operation ID. Cancelled/superseded history remains available for exact replay.

Claims, recovery, and state changes monotonically advance fencing tokens. Normal
claimed-job changes use a conditional SQL update matching workspace, state,
transition version, fence, expected worker, and an unexpired lease. Recovery is the
explicit privileged exception to requiring a live worker lease: it locks and
rechecks expired claims before replacing their fences. An old token cannot modify
a recovered/reclaimed job, even when the same worker identity is reused.

Timing uses `clock_timestamp()`, not transaction-start `now()` or the worker clock.
Future jobs cannot be claimed. Due jobs outside the configured inclusive lateness
window become blocked with `missed_schedule_window` and the effective window value
in sanitized metadata. Retry/recovery recheck snapshots and lateness. Acceptance
checks lateness again in its SQL update; a lease never extends the schedule window.

## Durable handoff integration

`record_handoff_acceptance` is a repository write boundary, not a Delivery adapter.
The authenticated application must acquire the same source/job locks, coordinate
execution-control and destination eligibility checks, and persist or verify the
Delivery-owned inbox in the **same session and transaction** before recording the
receipt. A receipt DTO alone does not establish durability. No production Delivery
inbox is created here; execution remains unavailable until that adapter and the
workload/control boundaries exist.

Handoff rejects stale snapshots, wrong job/destination/artist/timezone, mismatched
idempotency keys or fingerprints, expired leases, and missed windows. Any failure
must roll back the inbox and job operation together. After a definite stale/late
rejection, the application can block the claim in a fresh guarded transaction;
expired-lease recovery also blocks stale/late work. The repository does not commit
a blocked job alongside an accepted inbox. After an ambiguous acceptance
or commit outcome, read back durable job/inbox state; never automatically requeue
it. The internal retry allowlist covers database contention and interrupted local
preparation before acceptance, not provider failures or unknown commit outcomes.

## Verification

`apps/api/tests/test_scheduling_repository.py` requires `TEST_POSTGRES_URL` and uses
the existing isolated-schema PostgreSQL fixture. CI already provisions PostgreSQL
and runs the entire API suite. These tests cover concurrent claims and activation,
held-lock skipping, fencing on all claimed transitions, expiration/recovery,
duplicate claims, active-slot uniqueness, idempotency, bounds, workspace isolation,
snapshot drift, rollback, receipt bindings, and constant batch read-query counts.
The receiver table used in tests exists only in each disposable test schema.

From `apps/api` with `TEST_POSTGRES_URL` configured:

```powershell
python -m pytest tests/test_scheduling_repository.py tests/test_scheduling_contracts.py tests/test_scheduling_persistence.py -q
python -m ruff check src/labelos_api/repositories/scheduling.py tests/test_scheduling_repository.py
```

Local validation: the combined repository/contract/persistence run passed 223
tests. The subsequently added real-clock expiration test passed separately,
bringing coverage to 224 distinct tests, including 48 new PostgreSQL repository
tests. The two approval precedence cases also passed on rerun after their final
guard adjustment. Ruff, targeted Pyright, Black, and Markdown Prettier passed.
