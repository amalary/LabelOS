# Bounded Scheduling Engine processor

`services.scheduling_processor.SchedulingDueJobProcessor` is an internal,
workspace-scoped service. `run(workspace_id)` performs one recovery pass (at most
`batch_size` expired leases), one atomic claim pass (at most `batch_size` due jobs,
including blocked candidates), and one attempt per claimed job. Recovery and
claiming have separate bounded budgets. Batch size must be 1–1000; lease duration
and lateness policy are explicit inputs. It never polls, obtains credentials,
calls providers, or publishes content.

## Execution prerequisites

The host must authenticate its workload and construct `SchedulingWorker` with the
verified principal UUID, instance UUID, and workspace allowlist. These are internal
composition inputs, never user JSON or human impersonation. The separate
[trusted worker entrypoint](scheduling-worker.md) supplies Google OIDC authentication
and deployment scope. No production receiver or execution enablement is introduced.

Both trusted deployment controls and the workspace's
`scheduling_execution_controls.execution_enabled` must permit execution. A missing
row is disabled. Migration `202609152100` creates an empty control table and
activates no workspace. A certified transactional Delivery receiver must be
injected; missing and built-in unavailable receivers are rejected before claiming.
The deployable receiver factory remains unavailable.

Every transaction takes a PostgreSQL shared lock on the workspace control row
before source locks. Updating/deleting that row serializes emergency stops with
claims and acceptance. The check runs again per job. Deployment controls must stay
constant during an invocation; use the durable workspace switch for atomic stops.

## Transactions and recovery

Claiming uses parent-first locks and `SKIP LOCKED`, assigning an instance-scoped
worker ID, database-clock lease, and increasing fence. Claims commit before work.
Approval/channel/campaign records load in batches at claim time, then reload under
locks for each job transaction. The repository's `job_context` shares those locked
records with the handoff composer to avoid repeated approval reloads. It must not
span commits or a savepoint rollback followed by more ORM access.

Each job rechecks approval identity/revision, content revision/state, channel
instant/timezone/generation, effective artist/workspace, destination readiness,
due window, worker fence, and lease. Preparation accepts already materialized
immutable asset bytes. The final handoff write rechecks lease and lateness using
PostgreSQL wall-clock time.

The idempotency key is the existing workspace/job key. Correlation is UUIDv5 of
that key, so recovery and another worker reconstruct the same envelope without
including claim/fence values in its fingerprint.

The receiver must write its inbox in the caller's PostgreSQL transaction. A crash
after `accept()` returns but before the local update/commit rolls back **both**
inbox acceptance and the job update. The next attempt uses the same key/envelope;
an uncommitted receipt is not durable. Lost acknowledgement after commit leaves
both the receipt and `handed_off` job. `process_claim` reads that terminal state
without reconstructing subsequently edited content; receipt replay through the
existing acceptance boundary returns the original receipt. A receiver that commits
independently does not satisfy this contract.

Only `RetryableUnavailable` is safely requeued, or blocked if it became stale/late.
Committed history limits availability to three attempts (two automatic retries);
the third nonacceptance blocks with `missing_durable_delivery_receiver`. Rollback
does not consume the budget. See [rollout policy](scheduling-reliability.md) for
defaults, explicit revalidation, legacy safety, retention and shutdown.
Terminal rejection and invalid payloads block with `handoff_contract_violation`;
validation failures retain stable reasons. Unknown exceptions and ambiguous commits
leave durable state for readback/lease recovery. Expired workers cannot write a
terminal transition. Each job owns a transaction, so individual failures do not
roll back or prevent later jobs.

## Observability and verification

Append-only transitions audit the workload principal/instance, version and safe
reason. Realtime uses `marketing.scheduling_job.*` events with scheduling status,
identifiers, correlation ID and safe reason only, committed with each transition. No publication fields
or published events are written. Fixed-outcome logs and `scheduling_batch_metrics`
provide counts and duration for log-based metrics. Exception messages, content,
asset bytes, credentials and destination objects are excluded. See
[scheduling-observability.md](scheduling-observability.md) for metric definitions
and the calendar projection contract.

With `TEST_POSTGRES_URL` pointing to a disposable PostgreSQL database, run from
`apps/api`:

```powershell
python -m pytest tests/test_scheduling_processor_postgres.py tests/test_scheduling_processor_migration.py -q
```

Tests cover concurrent bounded processors, execution gates, expired leases/stale
workers, acceptance rollback, lost acknowledgements/duplicate receipt replay,
partial failures, retryable/terminal outcomes, lateness, invalidation/control races,
safe database columns, audit/outbox atomicity, and migration round trips.
