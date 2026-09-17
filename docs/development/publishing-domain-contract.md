# Publishing Delivery domain (Stage 1)

The architectural boundary remains:

`MarketingContentItem / MarketingContentItemChannel → Approval → Scheduling Engine → Publishing Delivery → Provider Adapter → External Provider`

`labelos_api.publishing.contracts` introduces pure, frozen dataclasses and string
enums, following `scheduling.contracts` and the existing service value objects.
There is no receiver implementation, database change, service endpoint, worker,
provider execution, retry timer, media upload, YouTube integration or frontend.
The deployable scheduling receiver remains unavailable.

## Ownership and existing architecture

- Marketing Content owns authored content and channel targeting. Approval owns
  authorization of a specific content revision. Neither its legacy publication
  fields nor assisted completion fields are evidence for this domain.
- Scheduling owns planning, activation, timing, jobs, scheduling leases/fencing,
  cancellation, replacement and supersession. Delivery retains job, revision and
  generation references as immutable provenance; it does not evaluate due times,
  recover scheduling claims, replace jobs or write scheduling state.
- Delivery owns one intended external side effect and its execution history.
  `handed_off` means durable acceptance at transaction commit, never `published`.
  Existing `PublishingDeliveryAcceptancePort` and canonical envelope remain the
  integration boundary. No parallel acceptance protocol is introduced.
- Social Account Connections own destination identity, connection health and
  credential references. Existing connection adapters do not publish. Future
  delivery adapters will normalize outcomes without leaking provider behavior
  into this domain. Credentials and tokens, including credential references,
  have no fields in these values. Arbitrary metadata, error strings and provider
  payloads are also excluded.
- Existing service authorization resolves an actor's workspace/campaign
  capabilities; repositories scope queries to workspace. The domain checks
  explicit caller scope and all attempt/evidence bindings, but is not an RBAC
  replacement and cannot establish database relationship ownership from UUIDs.
- Existing scheduling mutations use caller-owned transactions, append-only
  `SchedulingJobTransition` audit history and the `RealtimeEvent` outbox. Delivery
  should follow those conventions; Stage 1 emits no audit/realtime events.
  Workspace is persisted as `organization_id` on older content/connection rows
  and as `workspace_id` on scheduling rows, both referencing organizations.

## Domain values

| Value                   | Meaning                                                                                                                                                                      |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PublicationIntent`     | Required workspace, scheduling job, content item/channel, destination, approval, approved revision, schedule generation and canonical envelope fingerprint. One target only. |
| `Publication`           | Stable ID, immutable intent, creation time and ordered transition history. State is derived and validated on construction; arbitrary state assignment is unavailable.        |
| `PublicationAttempt`    | One actual execution start: ID, workspace, publication, monotonically increasing attempt number and UTC start time.                                                          |
| `PublicationEvidence`   | A typed, workspace/publication/attempt/destination-bound observation: outcome, source, UTC observation time, external post ID for success or an allowlisted failure reason.  |
| `PublicationTransition` | An immutable operation and UTC occurrence time carrying either an attempt start, an observation, or cancellation.                                                            |

Attempt starts and observations are separate append-only facts. Completion never
rewrites an attempt or its previous observations. Reconciliation appends evidence
against the same attempt and never pretends to be another external delivery.
Retries append a new attempt with a new ID and the next number, retaining the
publication ID, destination, content revision and fingerprint. All history is
validated when reconstructed, including legal edges, timestamps, sequence,
scope, evidence classification and latest-attempt binding. `transition` returns a
new immutable aggregate and leaves the prior one intact. This is a small domain
representation, not a new event store or persistence framework.

## Lifecycle

Creation starts at `pending`, with no attempts or provider success implied.

| From                       | Operation             | To                     | Guard                                                                                                             |
| -------------------------- | --------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------- |
| pending                    | start                 | processing             | Append first bound attempt.                                                                                       |
| retryable_failure          | retry                 | retrying               | Append next bound attempt; same publication intent.                                                               |
| processing, retrying       | confirm_success       | published              | Authoritative provider response or reconciliation confirms external publication and supplies an external post ID. |
| processing, retrying       | fail_retryable        | retryable_failure      | Provider response/reconciliation confirms no publication occurred and classifies failure as retryable.            |
| processing, retrying       | fail_permanently      | permanent_failure      | Provider response/reconciliation confirms no publication occurred and classifies failure as permanent.            |
| processing, retrying       | require_manual_action | manual_action_required | Outcome is unknown, including interrupted execution or an ambiguous response.                                     |
| manual_action_required     | confirm_success       | published              | Authoritative reconciliation confirms publication for the same attempt.                                           |
| manual_action_required     | fail_retryable        | retryable_failure      | Authoritative reconciliation confirms absence of publication and safe retry classification.                       |
| manual_action_required     | fail_permanently      | permanent_failure      | Authoritative reconciliation confirms absence of publication and permanent failure classification.                |
| pending, retryable_failure | cancel                | cancelled              | Respond to an authorized Scheduling cancellation only where no side effect is possible.                           |

`published`, `permanent_failure` and `cancelled` are terminal, with no outgoing
edges. Every other edge, including self-transitions, is rejected. `retrying`
means an actual retry attempt is executing; it is not a retry scheduling queue.
The core selects neither a retry deadline nor a retry budget.

`manual_action_required` is deliberately nonterminal. It is a reconciliation
hold, not authorization to manually publish a duplicate or blindly retry. It
cannot be cancelled until reconciliation establishes nonpublication and enters
`retryable_failure`. Cancellation during execution cannot prove that a provider
did not publish; cancelling a scheduling job after acceptance cannot undo a
publication. Scheduling continues to own cancellation intent and coordination.

`transition_target` checks the graph only. `Publication.transition` additionally
validates the complete evidence/history invariants. Future mutation services must
use the aggregate guards, not treat the graph helper as execution authorization.

## Evidence and trust assumptions

Success requires typed evidence from a trusted adapter/service confirming the
external publication, not merely an HTTP success code, queued provider task,
schedule activation, handoff receipt or human assertion. The external post ID is
bounded, excludes control characters and is hidden from representations. It must
be a non-secret identifier; syntactic validation cannot distinguish a token
deliberately placed in an identifier field. Raw responses must never be used to
construct these values without normalization.

Retryable and permanent failures both assert authoritative nonpublication. An
ambiguous timeout or lost response must be classified `unknown`, even if its
network error looks transient. An execution interruption can only yield unknown.
Once held for manual action, only reconciliation evidence can resolve it. A
future adapter must actually establish these facts; these pure values do not
contact providers or cryptographically prove an observation. They must never be
accepted directly from public request JSON. A definitive failure requiring
credential repair may remain retryable until the future service establishes
readiness; Stage 1 does not automate that action.

## Stage 2: Database Foundation requirements

The domain is ready for database implementation, not production delivery.

1. Persist Publication, immutable attempt starts, append-only observations/history
   and state projection in the existing SQLAlchemy/Alembic database package.
   Use timezone-aware UTC, explicit enum/check constraints, workspace composite
   foreign keys and restrictive deletion consistent with scheduling. Scope all
   publication/attempt reads and writes to the authenticated workspace. Validate
   content/channel, approval/revision, destination and source job relationships.
2. Retain the existing complete canonical handoff envelope, schema version,
   fingerprint, correlation ID and idempotency key in a delivery-owned inbox.
   The domain fingerprint is not a substitute for durable payload bytes. Reuse
   `labelos:scheduling:v1:{workspace_id}:{job_id}` from the existing request, with
   a unique workspace/job-to-publication mapping. Same key/fingerprint returns
   the original receipt and publication; different fingerprint is a conflict.
   Acceptance, publication creation and Scheduling's handed-off transition must
   commit together through the existing port/session contract.
3. Enforce uniqueness of attempt ID and `(workspace, publication, number)`, one
   active attempt per publication, immutable intent/history and conditional
   version updates. Concurrent calls on immutable Python snapshots alone do not
   prevent duplicate execution. Persist attempt starts before any later provider
   I/O; persist outcome/state/audit/outbox atomically afterwards. Do not hold
   scheduling leases or database transactions open across provider calls.
4. Add durable operation IDs/transition versions and transactional outbox records
   using the existing audit/realtime conventions. Domain replay is not a durable
   command receipt. Expose only allowlisted identifiers, state and safe reasons.
5. Keep receipt/publication mapping stable through retry and readback. A cancelled
   or replaced schedule must not mutate accepted intent or erase attempt history.
   Supersession authorization remains in Scheduling. Retention/deletion and
   reconciliation concurrency need persistence-level tests.

Cross-record ownership, deduplication, durable immutability, transactional
concurrency, authenticated workload execution and authoritative provider
verification remain obligations of later stages. This stage intentionally makes
no database migration or production readiness claim.

## Verification

`apps/api/tests/test_publishing_contracts.py` covers every state/operation pair,
terminal states, acceptance versus delivery, retry lineage, ambiguous outcomes
and reconciliation, cancellation, workspace/target/attempt mismatches, stale or
duplicate attempt results, immutable history, required identities and revisions,
fingerprint validation, UTC chronology and exclusion of arbitrary secret fields.

Run from `apps/api`:

```powershell
python -m pytest tests/test_publishing_contracts.py -q
python -m ruff check src/labelos_api/publishing tests/test_publishing_contracts.py
python -m black --check --no-cache --workers 1 src/labelos_api/publishing tests/test_publishing_contracts.py
```

Root `pnpm exec pyright` includes the publishing package. Existing API tests cover
the unchanged Marketing Content, Approval, connection, Scheduling, authorization
and realtime boundaries; PostgreSQL integration requires `TEST_POSTGRES_URL`.

Stage 1 validation on 2026-09-16: all 132 publishing cases passed with 100%
statement and branch coverage. The full API suite passed 1,286 tests and skipped
212 PostgreSQL-dependent cases without a configured test database; it emitted 16
existing Windows event-loop policy deprecation warnings from Alembic. API-wide
Ruff, publishing Black, root Pyright, Markdown/JSON Prettier and diff whitespace
checks passed. PostgreSQL behavior is not verified by this run.
