# Publishing idempotency and duplicate protection (Stage 7)

Stage 8 adds durable failure classification and retry eligibility; see
[publishing retries](publishing-retries.md) for the current execution policy.

LabelOS provides one durable Publication and one serialized attempt history for
each accepted publication intent. It does **not** provide exactly-once external
publication. SQL commits and provider writes cannot be one atomic transaction.
An adapter's final noncreation evidence is a trust boundary, not something SQL
can verify.

## Identities and database protections

The existing Stage 2 schema already supplies the required durable protections;
Stage 7 reuses them without a redundant table or migration:

| Identity                    | Protection and meaning                                                                                                                                                           |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Scheduling acceptance       | `labelos:scheduling:v1:{workspace}:{job}`; unique workspace/key, workspace/job, and receipt ID on Publication                                                                    |
| Intended publication        | Unique workspace/channel/authorized revision/schedule generation, backed by a composite foreign key to the Scheduling job snapshot                                               |
| External request            | `labelos:publication:v1:{workspace}:{publication}`; derived from immutable persisted IDs and unchanged across attempts; only useful externally if the adapter/provider honors it |
| Delivery command            | Unique workspace/execution UUID on immutable PublicationAttempt; Stage 7 now uses the caller's retained command identity instead of generating a fresh one per invocation        |
| Attempt and observation     | Unique publication/attempt number, workspace/execution, workspace/operation, publication/transition version, and one start transition per attempt                                |
| Confirmed provider resource | Unique workspace/destination/external post ID; this detects conflicting local evidence but cannot undo a duplicate external write                                                |

Creation locks the source job and compares the complete canonical envelope,
fingerprint and destination identity on replay. Simultaneous creation returns the
same Publication/receipt. Publication, acceptance history and realtime outbox are
committed together through the Scheduling composer. A rolled-back acceptance
leaves no independent delivery chain. The low-level repository is not acceptance
authorization and must not be used as a receiver by itself.

Execution preserves lock order: source, job, destination, Publication. It checks
the command identity before preparation and again while holding the prepared
Publication lock. The unique execution constraint handles cross-publication races
even when both prechecks saw an unused ID. Attempt/start commits before provider
I/O; outcome, projection, transition and realtime event commit afterwards.
There is no SQL lock held across network I/O.

PostgreSQL triggers prevent mutation/deletion of retained identities and history,
reject attempts outside pending/retryable states, serialize attempt insertion,
and reject mutation of published/permanent/cancelled Publications. Deferred
constraint triggers require complete matching history at commit. These guarantees
require the supported PostgreSQL READ COMMITTED transaction path with constraints
and triggers enabled. SQLite is useful for behavior tests, not concurrency proof.
Do not delete deduplication records or reset terminal state to retry work.

## Command replay versus intentional retry

`DeliveryOrchestrator.execute` accepts `execution_id` and `expected_version`.
The trusted host must persist one command UUID before enqueueing and carry that
same UUID through every queue redelivery, worker restart and HTTP retry. Generating
a new UUID inside a delivery handler defeats command deduplication.

Omitting the ID uses UUIDv5(publication ID, `labelos:publication:initial:v1`), a
stable initial command. It cannot implicitly retry a failed attempt. Consumed
commands raise `DeliveryIneligible("execution_already_started")`; reuse for a
different Publication raises `execution_identity_conflict`. These are fixed
nonexecution outcomes, not reasons to mint another command. A duplicate arriving
while another worker starts can instead see `publication_not_executable`.
Read back the scoped Publication to decide whether work completed or needs
recovery; never interpret a duplicate exception as provider success.

A deliberate retry requires all of:

- The same Publication in `retryable_failure`, supported by final noncreation
  evidence, and current content/destination authorization.
- A **new, durably retained** execution UUID.
- `expected_version` equal to the observed failure version.

For example, after a first attempt fails at version 2, pass the retained retry
command ID and `expected_version=2`. Competing or delayed retry commands for that
version cannot silently retry a later failure. No retry loop or timer is added.
A published item cannot be retried even with a new command ID and current version.
Intentional new content/revision/generation is a separate intent; this system does
not deduplicate identical text or media across independently authorized intents.

## Failure and duplication analysis

| Boundary                                                       | Durable behavior                                                                                                  |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Repeated scheduling acceptance/event                           | Same Publication and receipt; conflicting snapshot or envelope rejected                                           |
| Simultaneous creation                                          | Job lock serializes lookup/create; unique intent/job/key constraints are the final protection                     |
| Duplicate queue message                                        | Consumed execution ID cannot create another attempt, including after a retryable failure                          |
| Concurrent workers                                             | Locked preparation and versioned transitions allow one start; no in-flight lease takeover                         |
| Worker or manual retry                                         | Requires a new command and the exact retryable failure version; published/unknown work cannot execute             |
| Acceptance or start rollback                                   | No external call occurred; replay may start only if no start committed                                            |
| Lost acknowledgement of start commit                           | Caller propagates failure without invoking the provider; readback distinguishes pending from committed processing |
| Crash after start, before external call                        | Processing remains blocked; recovery conservatively treats the result as unknown                                  |
| Provider accepts, response is lost                             | Unknown outcome becomes `manual_action_required`; no blind retry                                                  |
| Timeout, malformed result, unhandled provider exception        | Unknown, unless the adapter has authoritative final noncreation evidence                                          |
| Provider success then crash/rollback before result persistence | Committed attempt remains processing; recover and reconcile that attempt, never issue a fresh publication         |
| Success persisted, message replayed                            | Terminal state plus consumed command and database guards prevent execution                                        |

Cancellation/process death can bypass ordinary exception handling. Such an attempt
remains processing/retrying, which also blocks execution. That is deliberate
conservative duplicate protection, at the cost of availability.

## Recovery and reconciliation

`recover_interrupted(sessions, workspace_id=..., publication_id=...,
execution_id=..., expected_version=...)` records an append-only unknown observation
for the matching latest attempt. It writes no provider request, creates no new
attempt, and is repeatable after quarantine or confirmed success without extra
history. Wrong executions and stale versions cannot quarantine another attempt.

This is a **trusted host operation**: establish that the original executor has
stopped and cannot resume before invoking recovery. A timestamp, request timeout
or expired queue lease is not sufficient. SQL fencing cannot stop a process already
authorized to send an external request. No automatic stale-attempt sweeper is
introduced. If an operator prematurely quarantines a live process, late evidence
is version-rejected and the item needs reconciliation; never grant a retry while
that process could still send its original write.

After quarantine, `reconcile` uses the registered adapter's capability and retained
publication/attempt identity. It never calls publish. Confirmed success records
the external ID on the existing attempt. Final noncreation can produce a retryable
failure; an eventual-consistency miss, pending operation or expired receipt cannot.
Unsupported, ambiguous, or failed lookup leaves the item blocked. Concurrent stale
lookup results cannot overwrite newer evidence. Direct `record_evidence` is also
trusted internal input, not a user-supplied assertion or public retry endpoint.

YouTube's current adapter uses multipart `videos.insert`, with no provider
idempotency parameter or retained resumable session. There is no supported lookup
by the LabelOS key in this path, so the adapter advertises reconciliation as
unsupported. Caption/time searches are not proof of absence. Google's
[insert reference](https://developers.google.com/youtube/v3/docs/videos/insert)
defines the API parameters; its separate
[resumable protocol](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol)
can query an upload using a previously obtained session URI. Adopting that protocol
would require a durable, protected session-receipt contract and is not implemented
by this stage. Neither capability justifies a blanket exactly-once claim.

For an ambiguous YouTube upload, inspect the connected destination and obtain
authoritative evidence binding any discovered resource to this attempt. A trusted
operator integration may record verified success as reconciliation evidence. If
the outcome cannot be established, retain `manual_action_required`; do not reset
the item, invent absence, clone it, or repeatedly upload it to clear the queue.
The public operator interface and authorization/audit workflow remain future work.

## Verification and Stage 8 handoff

`tests/test_publishing_idempotency_postgres.py` uses independent PostgreSQL
transactions and controlled provider barriers for duplicate messages during I/O,
replay after success/failure, simultaneous creation, competing versioned retries,
manual retry after success, crash boundaries, result rollback, unknown timeout,
repeated recovery and reconciliation on the original attempt. The existing
publishing persistence and delivery suites cover raw SQL guards, deferred commit
validation, migration round trip, acceptance rollback and stale evidence.
YouTube/provider tests verify normalized results and explicit retries with stable
provider keys. Providers are simulated; no live upload is performed.

Validation on 2026-09-16 (Python 3.14, local PostgreSQL 17.5): **142 passed**
with PostgreSQL enabled across the idempotency, persistence, delivery and handoff
suites, including all **14 new Stage 7 cases** and the migration round trip.
The separate provider/YouTube/domain run passed **302 tests**. Neither final run
skipped tests. API-wide Ruff, root Pyright, scoped Black, documentation Prettier
and `git diff --check` passed. This is a focused regression, not a full API or
deployed-provider certification; CI uses its configured PostgreSQL/Python versions.

From `apps/api`, set `TEST_POSTGRES_URL` to disposable PostgreSQL and run:

```powershell
python -m pytest tests/test_publishing_idempotency_postgres.py tests/test_publishing_persistence.py tests/test_delivery_orchestrator.py tests/test_scheduling_handoff_postgres.py -q
python -m pytest tests/test_publishing_providers.py tests/test_youtube_publishing.py tests/test_publishing_contracts.py -q
```

Duplicate worker messages are modeled as repeated real orchestrator invocations;
these tests do not provision or certify an external queue service.

Stage 8 can use these primitives for worker/retry orchestration. It must persist
command identities, distinguish queue redelivery from a newly authorized retry,
retain expected failure versions, establish executor shutdown before recovery,
and route unknown outcomes to reconciliation. This stage does not enable an
unattended production worker. Production rollout still requires a real approved
media smoke test with upload consent and an operational reconciliation procedure.
