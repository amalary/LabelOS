# Publishing Delivery database foundation (Stage 2)

Stage 1's domain and state machine are unchanged. Storage lives in
`labelos_database.publishing_models` (re-exported by `models` and the database
package); the workspace-scoped repository is `labelos_api.repositories.publishing`.
No provider calls, receiver implementation, endpoint, worker, or scheduling
activation is introduced. The production handoff receiver remains unavailable.

## Schema and ownership

| Table                     | Responsibility                                                                                                                                              |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `publications`            | One immutable accepted intent and delivery-owned inbox envelope, stable receipt, current lifecycle projection and transition version.                       |
| `publication_attempts`    | Immutable execution starts, ordered within the publication, with an opaque UUID execution correlation.                                                      |
| `publication_transitions` | Append-only operations and observations, including normalized outcome, failure reason, evidence source, observed/completion time, and optional HTTP status. |

The inbox is part of the publication row rather than a parallel copy of the
publication identity. It retains the **complete canonical envelope bytes**, schema
version, SHA-256 fingerprint, existing scheduling idempotency key, and correlation
UUID. Repository creation validates the existing canonical request contract. The
same workspace/job and envelope return the original publication and receipt;
a different fingerprint or envelope conflicts. Receipt readback is available by
workspace/job. No mutable Marketing fields are copied into alternate content rows.

Publication fields reference workspace, scheduling job, content item, channel,
destination, approval, authorized revision, and schedule generation. Provider is
bound to the canonical destination. Success projects the external resource ID and
observed publication timestamp; an optional public HTTPS URL can be supplied with
success evidence. Cancellation stores `scheduling_cancelled` and a timestamp.
Manual action stores `outcome_unknown` and a timestamp; its complete history
survives reconciliation even after the current hold fields are cleared.

Attempt completion does **not** overwrite an execution start. `observations` holds
the ordered transition records; `completed_at` is the first execution observation,
while `outcome`, `failure_reason`, and `retry_eligible` derive from the latest
observation. Thus unknown followed by successful reconciliation remains two facts
about one attempt. Retry eligibility describes evidence classification, not worker
authorization or an automatic retry schedule. A retry appends a new start.

## Relationships and retention

- `publications.workspace_id` references `organizations.id`.
- A composite FK to `scheduling_jobs` binds job ID, workspace, content, channel,
  destination, approval, revision, and generation together. Existing Scheduling
  composite FKs transitively bind these to the canonical Marketing and Approval
  records. This prevents individually valid IDs from forming a mismatched intent.
- A composite destination FK binds connection ID, workspace, and provider to
  `social_account_connections`.
- Attempts reference `(publication_id, workspace_id)`. Transitions use that same
  scope and bind `(attempt_id, publication_id, workspace_id)` to the attempt.
- All new FKs use `RESTRICT`. History has no ORM delete cascades; relationship
  collections are read-only. Update/delete triggers preserve intent, starts,
  observations, and terminal publication rows. Source deletion and workspace
  deletion cannot erase retained delivery history. Normal disconnect/health
  changes remain possible; provider-name changes are restricted.

There are no new artist, campaign, user, workspace, destination, credential, or
content entities. Actor authentication, capabilities, and authorized scheduling
cancellation remain caller responsibilities. Execution and operation identifiers
are UUIDs, not free-form worker descriptions or credential references.

## Constraints, indexes, and concurrency

Unique keys enforce one publication per workspace/job and per
workspace/channel/approved revision/generation; stable receipt and idempotency
mapping; one provider resource per workspace/destination; unique attempt ordering
and execution UUID; unique operation IDs and transition versions; and one start
transition per attempt. Provider-resource uniqueness is partial for non-null IDs.

Named checks cover the Stage 1 state/operation/outcome/reason/source allowlists,
legal transition edges, evidence shapes, success/failure classification, unknown
interruption outcomes, reconciliation source, timestamps, positive counters,
required cancellation/manual-action details, and bounded payload/HTTP status.
Indexes cover workspace/status listing, content history, destination lookup,
attempt order, and observation order. Two supporting unique indexes on canonical
Scheduling and Social Connection tables enable the composite FKs.

Repository mutations lock the publication and perform a conditional version/state
update. Attempt insertion also locks the publication on PostgreSQL and requires
contiguous numbering and authoritative retryable failure before another start.
The history remains append-only; no active flag needs to be rewritten on a start.
PostgreSQL deferred constraint triggers reject commits with a projection missing
its matching history, differing success evidence, or an orphan attempt start.
SQLite exercises repository behavior and immediate guards but does not provide
these deferred commit checks or PostgreSQL concurrency guarantees.

Every creation and transition writes an allowlisted `marketing.publication.changed`
record to the existing `RealtimeEvent` outbox within the same caller-owned
transaction. A savepoint rolls back partial publication mutations on errors. No
method commits or dispatches an event. Failed or uncertain commits require scoped
readback; duplicate mutation operation IDs are rejected, not interpreted as
permission to execute again.

## Migration and validation

Revision `202609162200` follows `202609152100` in the existing linear chain. It
creates only the three delivery tables, their guards, and the two supporting
indexes. It imports no mutable application schema. Older migrations are unchanged.
Downgrading removes this revision's history and storage, preserving canonical
source tables; use the downgrade only with an intentional data-retention decision.

Validation uses an isolated local PostgreSQL 17 cluster and the existing
`TEST_POSTGRES_URL` schema-isolation fixture, plus SQLite behavior tests. The new
migration test exercises the full chain, downgrade/re-upgrade, schema inspection,
and repository writes against migrated tables. Additional tests cover concurrent
creation/start races, stale versions, rollback, reconciliation, source deletion,
unsafe URL rejection, immutable history, workspace ownership, and constraints.

CLI verification on the disposable database:

```powershell
python -m alembic -c ../../packages/database/alembic.ini upgrade head
python -m alembic -c ../../packages/database/alembic.ini downgrade 202609152100
python -m alembic -c ../../packages/database/alembic.ini upgrade head
python -m alembic -c ../../packages/database/alembic.ini current
python -m alembic -c ../../packages/database/alembic.ini heads
```

All migration operations succeeded; current and the single head are
`202609162200`. The final focused run passed 212 tests: 132 unchanged Stage 1
cases and 80 persistence cases across SQLite and PostgreSQL. Ruff, Black, root
Pyright (including the new repository/models), Prettier, and diff whitespace
checks passed. The full API regression run with live PostgreSQL passed 1,743
tests, with 16 existing Windows/Alembic event-loop deprecation warnings. The
focused run includes the final additional URL and source-edit cases. No
PostgreSQL tests were skipped in these configured runs.

## Security and Stage 3 boundary

No OAuth tokens, refresh tokens, credentials, credential references, arbitrary
error strings, raw provider bodies, or free-form response metadata have storage
fields. Response diagnostics are limited to an integer HTTP status. URLs must be
HTTPS without user info, query, fragment, control characters, or nonstandard ports;
future adapters must also establish that a URL belongs to the provider and is safe
to expose. Identifiers must be normalized non-secret values: syntax cannot identify
a token deliberately supplied as a resource ID. The canonical inbox contains
approved authored content/media; treat it as private workspace data, avoid logging
payloads or database exception parameters, and apply the normal database access,
backup, and retention controls. Arbitrary authored text is not credential storage.

The repository scopes every read and mutation, and composite FKs enforce ownership
for direct writes. This follows existing application isolation conventions; no
new database row-level-security policy is claimed. Database constraints cannot
prove an adapter's assertion that an external side effect occurred.

Stage 3 can begin on this foundation. It must implement the existing
`PublishingDeliveryAcceptancePort`, call repository creation in the **same session
and transaction** as Scheduling's handoff transition, preserve the original receipt
on replay, and perform existing authorization, eligibility, control, lease, and
cancellation checks before acceptance. Repository creation alone is deliberately
not acceptance authorization. Durable start commit must precede provider I/O;
provider calls must not hold database locks or Scheduling leases open. Unknown
execution/commit outcomes require reconciliation, never a blind retry.

Architecture issues identified: legacy Marketing publication fields are not
Delivery evidence; completion and reconciliation require separate retained facts;
workspace naming differs between older and Scheduling tables; retained history
intentionally blocks hard deletion; and SQLite's legacy transaction behavior needs
an explicit BEGIN in rollback tests. Existing PostgreSQL production conventions
avoid that SQLite-only savepoint issue. Social Connection metadata sync can still update `external_account_id` (see
`social_account_service._apply_metadata_sync`). This schema intentionally references
the canonical connection rather than duplicating its account data; Stage 3 must
establish a stable destination-identity policy and verify that credential/account
identity has not changed before external I/O. This is an execution prerequisite,
not a reason to enable delivery now. Delivery execution and trusted provider
normalization remain later-stage work.
