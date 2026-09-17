# Publishing Delivery Orchestrator (Stage 3)

Stage 4 replaces the original provider seam with the
[Provider Adapter Contract](publishing-provider-adapter.md): typed requests/results,
an empty-by-default registry, local validation, and explicit reconciliation. The
Stage 3 provider-seam description below records the original design; current
execution takes `registry=...` and unknown providers return `unsupported_provider`
without starting an attempt. Production delivery remains unavailable.

`DeliveryOrchestrator` is an internal application service. It builds on the
[Stage 1 domain](publishing-domain-contract.md),
[Stage 2 repository](publishing-database-foundation.md), and existing
[Scheduling handoff composer](scheduling-delivery-handoff.md). It adds no endpoint,
polling loop, due-time selection, Scheduling lease management, retry deadline, or
provider-specific API calls. Production receiver configuration remains
`unavailable`; the default publication provider is disabled.

## Acceptance and ownership

The authenticated workload host calls `accept_execution` with its workspace-scoped
Scheduling repository, prepared canonical request, worker/fence, and trusted
transaction-local execution controls. That method delegates to the existing
Scheduling composer, supplying a private `PublishingDeliveryAcceptancePort`
implementation. Do not instantiate that private receiver or expose these inputs
as user JSON. The existing Scheduling processor and receiver factory are unchanged;
deployment wiring remains a later integration decision.

Scheduling retains all authority over claiming, due windows, cancellation,
supersession, source approval, generation, and the final fenced handoff transition.
The private receiver creates a `pending` Publication and its outbox event through
the Stage 2 repository. It rejects missing account identity and refuses to repair
an orphan repository row or fabricate acceptance for an already handed-off job
whose Publication is missing. A repository insert alone is not acceptance.

The caller owns the outer transaction. The existing composer savepoint encloses
Publication creation, its outbox event, Scheduling's `handed_off` transition, and
Scheduling history/outbox. A rejection, final fence failure, or receiver failure
rolls them back together. An outer rollback removes them all. No service or
repository commits part of that acceptance independently. PostgreSQL READ COMMITTED
and the existing source/campaign/channel/approval/job/destination lock order remain
required for mutations.

## Idempotency and execution eligibility

The existing unique workspace/job and workspace/channel/revision/generation keys
enforce one intended Publication per scheduling execution and target. The
canonical `labelos:scheduling:v1:{workspace}:{job}` key, full envelope bytes,
fingerprint, and stable receipt are retained. Exact replay returns the original
receipt, including after publication succeeds, source edits, or execution shutdown.
A different envelope or fingerprint is a conflict; accepted content is never
overwritten. Source/job locks serialize concurrent acceptance before the unique
constraints provide the final storage guard.

`prepare_execution` consumes an explicit Publication ID. It reloads canonical
source records in workspace scope, then locks the Publication after the destination.
It requires a matching durable handoff receipt and checks current approval,
revision, parent state, schedule generation/intent, effective artist, channel,
destination compatibility, connection health/capability, and content/media bytes.
Content must contain nonblank copy, media, or structured hashtags; provider-specific
format requirements remain the adapter's responsibility.
Only `pending` or authoritatively `retryable_failure` Publications can execute.
Published, executing, cancelled, permanently failed, or unknown-outcome work cannot
start again. Prepared contexts hide the envelope and account fingerprint from repr;
they contain no credentials or credential references.

Preparation does not evaluate due time, recover a Scheduling claim, or reactivate a
job. Its context is a transaction-local observation, not a durable execution permit.
`execute` repeats preparation in the transaction that records the attempt start.
Invalid work remains retained for history; the service does not invent cancellation
intent or a new scheduling transition. Scheduling currently refuses cancellation
and supersession after `handed_off`; coordinated postacceptance cancellation remains
future work. Current source generation/intent drift nevertheless blocks execution.

Migration `202609162300` adds an immutable, nullable `destination_identity` to
Publication. New orchestrated acceptances require a nonblank external account ID
and store SHA-256 over canonical `[provider, external_account_id]`. Preparation
compares it with the currently locked connection. Account replacement under the
same connection UUID therefore cannot silently redirect accepted work. Metadata
edits or credential refresh that preserve account identity do not themselves
invalidate the binding. Legacy rows retain null and fail closed for execution;
the migration does not backfill a historical identity it cannot establish.

## Provider seam and lifecycle transactions

`PublicationProvider` accepts an immutable context and bound attempt and returns
Stage 1 normalized evidence. The only shipped implementation is disabled. Internal
tests inject deterministic providers; no production configuration enables them.

`execute` coordinates one explicit invocation:

1. In a short transaction, revalidate accepted work and lock the Publication. If
   the provider is disabled, return `provider_execution_disabled` without creating
   an attempt or changing state. Otherwise append a unique attempt/start transition
   and outbox event with the repository's version guard; commit.
2. Call the trusted provider outside any database session, locks, or Scheduling
   lease. Adapters must bind resolved credentials to the expected destination
   identity before external I/O.
3. In a new transaction, append evidence and update lifecycle/history/outbox
   atomically. Provider exceptions are normalized to `unknown` interruption and
   `manual_action_required`; they are not classified as safe retries.

`record_evidence` also supports trusted reconciliation with the same scope,
attempt/destination bindings and expected version. It intentionally does not
recheck authoring approval: an actual outcome must remain recordable after content
changes. The unchanged aggregate validates evidence and legal transitions.

An explicit subsequent invocation can append a retry only after authoritative
nonpublication has established `retryable_failure`. There is no retry loop or
timer. Concurrent invocations serialize on the Publication and cannot both start
the same pending execution. Every retry retains Publication identity and envelope.

Internal idempotency does **not** promise exactly-once external delivery. A process
death, task cancellation, invalid adapter evidence, or failed/unknown result commit
can leave a committed attempt in `processing`/`retrying`. A later execute call
refuses it. A recovery host must establish interruption and reconcile that same
attempt; it must not start another delivery. An unknown start commit propagates
before provider I/O. Unknown outer acceptance commits require readback by the
original job/key/receipt. Provider-side idempotency, account/credential races,
verification, and recovery require Stage 4 integration and tests.

## Files and verification

- `services/delivery_orchestrator.py`: acceptance composition, preparation,
  execution transaction boundaries, and evidence coordination.
- `publishing/execution.py`: safe context/result values and disabled provider seam.
- `repositories/publishing.py`: optional immutable destination fingerprint at creation.
- Database `publishing_models.py`, `publishing_guards.py`, and migration
  `202609162300_delivery_destination_identity.py`: persisted identity binding.
- `test_delivery_orchestrator.py`: PostgreSQL service/repository integration tests.
- `test_publishing_persistence.py`: extended migration roundtrip/guard parity checks.
- Root `pyrightconfig.json`: includes the new service in type checking.

Tests cover normal creation, exact and concurrent replay, conflicting replay,
cancelled/superseded work, invalid approval, revision/content/generation drift,
missing and actual cross-workspace references, destination/account changes,
already-published work, disabled execution, concurrent attempts, explicit retry,
unknown outcomes, reconciliation, and acceptance/start/result rollback. The
provider test reads and locks the committed attempt using a different session
during delivery, verifying that provider I/O occurs outside the start transaction.

Run from `apps/api` with `TEST_POSTGRES_URL` targeting a disposable PostgreSQL
database (fixtures isolate and remove schemas):

```powershell
python -m pytest tests/test_delivery_orchestrator.py tests/test_publishing_contracts.py tests/test_publishing_persistence.py tests/test_scheduling_handoff.py tests/test_scheduling_handoff_postgres.py -q
python -m ruff check .
```

Validation completed on 2026-09-16: the affected Publishing/Scheduling regression
passed 526 cases using live PostgreSQL and SQLite where supported. The final
orchestrator suite, including empty-content checks, passed all 38 PostgreSQL cases.
Migration upgrade/downgrade, frozen guard parity, API-wide Ruff, scoped Black,
root Pyright, documentation/config Prettier, and diff whitespace checks passed.
The full API run was stopped in favor of this affected-suite regression; no full
API regression result is claimed for Stage 3.

Stage 4 can implement trusted adapter normalization, credential/account binding,
provider idempotency and reconciliation, and authenticated deployment integration.
Keep production delivery disabled until those provider and recovery guarantees
are validated. This stage supplies the application boundary and lifecycle
transactions, not production delivery readiness.
