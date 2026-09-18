# Publishing Stage 9: worker execution and concurrency safety

The production Scheduling host now supplies pending Publications through
`DELIVERY_RECEIVER_BACKEND=publishing`. See the
[composition and rollout guide](scheduling-publishing-composition.md). Publishing
execution remains separately enabled and scoped; intake does not invoke providers.

The [Stage 10 recovery workflow](publishing-recovery.md) adds manual reservations
that exclude worker claims and durable remediation grants consumed by new attempts.
Unsupported adapters now record terminal failures instead of remaining pending.

`PublishingProcessor` performs bounded, workspace-scoped sweeps independently of
Scheduling. It reuses `DeliveryOrchestrator` for source/approval/account checks,
provider adapters, normalized evidence, durable retries, journal and outbox.
Scheduling's lease ends at acceptance. Publishing follows its established
PostgreSQL `SKIP LOCKED`, database-clock, short-transaction and fencing patterns,
without copying Scheduling's eligibility engine, principal, receiver or job state.

## Ownership and transactions

Migration `202609170200` adds `publication_leases`, keyed by publication with a
tenant-bound foreign key, owner UUID, monotonically incremented fencing token,
expiry and persistent interruption marker. Execution metadata is separate from
the immutable lifecycle journal. New acceptance creates the lease row atomically;
the migration backfills existing publications without rewriting their history.

The production database is PostgreSQL at READ COMMITTED. All ownership operations
lock **publication before lease**. Preparation retains the existing source → job
→ destination → publication order. Claim/heartbeat/recovery transactions never
acquire source locks after acquiring publication locks.

| Boundary     | Durable work and locks                                                                                                                                                                                                                                              |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1: claim    | Select one eligible publication with `FOR UPDATE OF publications SKIP LOCKED`; install owner, increment fence, set expiry using PostgreSQL wall time; commit. Claims are acquired just before processing, not leased as a batch that waits behind network calls.    |
| T2: start    | Revalidate source, approval, destination identity, lifecycle, retry time/deadline, command identity and lease ownership under locks. Append the immutable attempt/start, projection and outbox. Recheck fence/expiry after writes and commit before provider I/O.   |
| Provider I/O | No orchestration transaction, row lock or database connection spans the adapter call. Adapters retain their existing short credential transactions. A separate heartbeat renews ownership every lease-duration/3.                                                   |
| T3: outcome  | Lock publication; validate owner, fence and unexpired lease; append normalized evidence, retry decision, projection and outbox; recheck ownership; clear owner/expiry in the same transaction.                                                                      |
| Recovery     | Atomically take expired ownership with a higher fence. An unstarted pending/due retry can execute. A committed processing/retrying attempt is quarantined as uncertain, preserving its attempt and requesting reconciliation/manual action. No publish call occurs. |

Due retry selection and worker start eligibility use the database clock, not the
host clock. Future retries, expired budgets, blocked dispositions, published,
cancelled, permanent and manual-action publications are excluded. The existing
attempt guard enforces the maximum attempt count. A sweep visits each publication
at most once. Stable command IDs derive from publication and lifecycle version;
provider idempotency keys retain their existing publication identity across retries.

Cancellation is serialized with start on the publication row. If cancellation
wins, it revokes ownership, increments the fence and prevents provider execution.
If start has committed, cancellation of waiting work is rejected; an in-flight
external action cannot truthfully be declared cancelled. Lease checks also reject
unfenced direct execution/evidence while a worker owns the publication.

Approval invalidation discovered during execution preparation cancels waiting
Publications durably. The same applies to a replaced approved revision, an
ineligible parent state, or a withdrawn/superseded schedule intent. Migration
`202609170400` extends the existing cancellation reason constraint; no new state
or provider failure evidence is introduced. `pending` and `retryable_failure`
transition to terminal `cancelled`, with the safe refusal code retained in
`cancellation_reason`. Since cancellation is terminal and database-immutable,
that reason belongs to the aggregate's sole cancellation history fact.

The execution transaction retains source/approval/job locks, validates the
Publication version and worker fence/expiry, appends cancellation and the realtime
outbox event, clears retry metadata, and revokes the lease with a higher fence.
It commits normally instead of raising a preflight exception that would roll back
the disposition. No attempt is created; existing attempts and observations remain
intact. Expired or superseded workers cannot write the cancellation or override it.
Both worker polling and `retry_due` exclude cancelled work using their existing
status predicates. Invalid work may be claimed once to discover the disposition;
subsequent sweeps cannot reclaim it. A future retry is checked when it becomes due.

Accepted Scheduling redelivery still returns the original receipt and cancelled
Publication. It cannot create another Publication for the same intent. A newly
approved content revision follows normal Scheduling activation and handoff with
a new intent; historical cancellation is never reversed. History exposes the
cancellation timestamp/reason, realtime emits cancelled status and its reason,
and the calendar never treats cancellation as confirmed publication.

## Expiration, uncertain calls and shutdown

Expiration is permission to recover ownership, **not evidence of nonpublication**.
A stale executor cannot append authoritative evidence, renew, release or start
using its old claim. Recovering an in-flight attempt sets a persistent interruption
marker. Positive reconciliation can confirm publication; absence-based evidence
cannot authorize a retry while that marker remains. A paused executor or a
provider request may still finish after local cancellation or lease loss. This
conservative rule prevents duplicate execution without claiming exactly-once
delivery from a remote API that offers no such guarantee.

No automatic clearing of the interruption marker is provided. Operator resolution
must establish executor quiescence and authoritative final noncreation before a
future recovery workflow can authorize another attempt. YouTube's existing lack
of authoritative idempotency-key lookup still requires operator investigation for
uncertain uploads. Stage 9 persists that manual/reconciliation work; it does not
automatically poll providers or release ambiguous work.

Heartbeat failure cancels local execution and leaves its committed attempt for
recovery. Execution timeout has the same behavior. Unknown transaction commit
acknowledgements are not treated as permission to call the provider or retry.
SIGTERM/SIGINT stops new claims and drains the current bounded operation. Forced
process/task cancellation leaves claims recoverable after expiry. A committed
outcome and lease release remain atomic even if its acknowledgement is lost.

Existing trusted explicit `execute`, `retry_due` and stopped-executor recovery
interfaces remain compatible. Production recurring execution uses the new worker.
Historical processing attempts without Publishing ownership are intentionally not
automatically seized: stop legacy executors and use their established recovery
procedure before switching hosts. Deploy the migration before the new worker;
stop/drain Publishing workers before downgrading lease storage.

## Private job entrypoint

Run `python -m labelos_api.publishing_worker --execute` from an installed API
environment. This is a private process/job, with authorization supplied by the
deployment's process identity, DB permissions and credential-store IAM. There is
no public HTTP endpoint or caller-supplied workspace in a message body.

| Setting                             | Default                         |
| ----------------------------------- | ------------------------------- |
| `PUBLISHING_EXECUTION_ENABLED`      | `false`                         |
| `PUBLISHING_WORKER_WORKSPACE_ID`    | Required when enabled           |
| `PUBLISHING_WORKER_BATCH_SIZE`      | 25; maximum 1000                |
| `PUBLISHING_WORKER_LEASE_SECONDS`   | 120; range 1–3600               |
| `PUBLISHING_WORKER_TIMEOUT_SECONDS` | 300 per execution; range 1–3600 |

The host uses the existing session factory, OAuth provider registry and exact
credential-store composition. It requires asyncpg/PostgreSQL and disables SQL
echo. Production credential configuration retains existing validation. Scheduling
flags and worker settings do not enable Publishing. Missing provider capability
returns a bounded refusal and releases the unstarted claim. Output contains only
fixed status/reason codes and counts, never provider responses or exception text.
Deployment cadence and provider credentials are not enabled by this change.

## Verification and Stage 10 handoff

`test_publishing_worker_postgres.py` uses real independent PostgreSQL sessions and
mocked providers. It covers simultaneous processors, held/uncommitted exclusive
claims with SKIP LOCKED, workspace scope, prestart lease expiration, monotonic
fencing, stale renew/release/start/completion, lock-free provider I/O, recovery
while an old request is still running, crash/restart, future retry exclusion even
with a fast host clock, both cancellation orderings, duplicate prevention,
heartbeat renewal/loss, lost start/outcome commit acknowledgements and concurrent
due retries. Existing suites verify provider normalization, retry classification,
immutable journals, unique command identities and migration round trips.

Stage 10 can build on the worker and persisted retry/manual-action dispositions.
Deployment enablement, cadence and an operator workflow for ambiguous delivery
remain explicit integration tasks. No live provider calls are needed for these
concurrency checks.

Verified locally on 2026-09-17 against PostgreSQL 17 using isolated disposable
schemas: **17 worker concurrency tests passed, zero skipped**. Migration upgrade,
downgrade, metadata parity and seeded lease backfill passed; six host configuration
tests passed. The broader affected regression run passed **472 tests**, including
PostgreSQL/SQLite delivery, providers, retries and Scheduling handoff. The earlier
combined worker/idempotency/persistence run passed 107 tests. These runs overlap;
they are not a claimed total of distinct tests or a whole-API test run. API Ruff,
configured Pyright (including the new worker), Black, Prettier and
`git diff --check` passed. Provider calls were mocked throughout concurrency tests.
