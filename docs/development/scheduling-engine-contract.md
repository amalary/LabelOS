# LabelOS Scheduling Engine architecture and policy contract

Status: accepted contract, 2026-09-14. This document records the original phased
design; references to future implementation describe those phases. For current
implementation and verification, see the
[production-readiness audit](scheduling-production-readiness.md),
[rollout policy](scheduling-reliability.md), and [worker runbook](scheduling-worker.md).
The worker and persistence now exist; production execution remains disabled.
Implementation update, 2026-09-15: the
[durable handoff boundary](scheduling-delivery-handoff.md) resolves the v1 payload
normalization and asset-immutability policies below, adds typed acceptance outcomes
and transaction composition, and verifies a test-only durable receiver. Production
execution remains unavailable; no successful production receiver is configured.

This document is normative for the next implementation. It adds no job table,
migration, worker, queue, delivery inbox, configuration wiring, or API behavior.
The isolated [Python contracts](../../apps/api/src/labelos_api/scheduling/contracts.py)
encode the graph, approval/snapshot predicates, lateness boundaries, feature
controls, and acceptance port. They are not a complete authorization or execution
service. Existing parent status transitions continue to be planning operations.

## 1. Ownership and scheduling unit

One executable job targets one `MarketingContentItemChannel`. The channel's
`scheduled_at` is the sole canonical authoring intent. The parent's `scheduled_at`
is separate planning data; neither setting it nor moving the parent to `scheduled`
activates any channel. A future parent convenience command must explicitly list
channel IDs and activate a separate job for each, under the same eligibility rules.
If that command assigns times, those are material edits requiring subsequent approval.

Scheduling owns activation, due selection, validation, claim coordination,
cancellation, supersession, and durable handoff. Publishing Delivery owns execution
after acceptance. Social Account Connections owns destination identity, health,
and capability resolution. Content and Campaign Calendars are read projections.
The realtime outbox supplies notifications only; it is never scanned as a job queue.

Explicitly outside Scheduling: provider-specific API calls, media uploads,
credential retrieval/refresh, provider retries/backoff, rate limits, manual
publishing tasks/assignment/reminders, provider post IDs/URLs, publication history,
and `marketing.content.published` emission. `handed_off` means Delivery durably
accepted work, not that a provider published it. Scheduling never writes
`published_at`, `external_post_id`, or `external_url`.

## 2. Intent, immutable snapshots, identity, and lineage

Future storage must contain the following concepts (this is not a schema change):

| Record            | Required values and invariant                                                                                                                                                                                                                                         |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Channel intent    | Existing `scheduled_at`, explicit IANA authoring timezone, monotonically increasing `schedule_generation`, stable channel ID.                                                                                                                                         |
| Job snapshot      | Job/workspace/content/channel IDs; exact `content_revision`, authoritative `approval_request_id`, `schedule_generation`, UTC `scheduled_for`, authoring timezone, destination ID, effective artist context. Server derives these together from locked source records. |
| Coordination      | State; claim owner, monotonically increasing claim fence, database-clock lease expiry; structured blocked reason; transition version; durable receipt reference when handed off.                                                                                      |
| History           | Immutable activation actor/time/operation ID; predecessor job ID and lineage root; immutable transition records with reason and actor; historical snapshots retained after removal.                                                                                   |
| Delivery envelope | Versioned canonical immutable content payload, fingerprint, stable idempotency key, acceptance receipt. Delivery retains the complete payload, not pointers to mutable copy/assets alone.                                                                             |

`scheduled_for` is indexed for due processing and immutable after activation.
There is no endpoint that edits it independently. Each material mutation of a
channel increments that channel's generation; time or authoring timezone changes
are material even when the UTC instant is unchanged. Every existing material
parent/channel change still increments the parent's `content_revision`, which
invalidates all channels authorized by that revision. Unchanged channels need not
increment generation when a different channel changes; revision checks fence them.
Activation with unchanged intent uses the existing generation; a new activation
after cancellation uses a new job ID and lineage entry, not a rewritten snapshot.

Only one occupying job per channel: `pending`, `claimed`, and `blocked` all occupy
the active slot. Blocked work must be cancelled, superseded, or explicitly
revalidated before another job can occupy it. Future database uniqueness must
enforce this in addition to the locked conflict check. Terminal jobs are immutable.
A unique workspace-scoped activation operation ID makes command retries return
the original result; a reused operation ID with different inputs is a conflict.
An already handed-off revision/generation must not be activated again. A new
publication intent requires a material revision and fresh approval.

**Identity prerequisite:** replace
`repositories.marketing_content.replace_channels`, which currently deletes every
channel then recreates them, before introducing executable channel foreign keys.
Carry channel IDs through read/edit/write contracts. Reconcile by validated ID;
for a legacy ID-less payload only use an unambiguous existing `(channel, placement)`
match, otherwise reject and require explicit identity. Do not infer identity by
list order or destination. Unchanged logical channels keep IDs; same-ID content or
destination edits keep identity but invalidate jobs. Removed channels are retired
and active jobs cancelled. A materially replaced logical channel gets a new ID;
old active jobs become superseded with replacement lineage. Retain tombstones or
use restricted deletion so terminal job history and references survive. Never
cascade-delete jobs/history. No-op replacement and reordering preserve IDs,
revision, generation, and approval.

## 3. Eligibility contract

Activation is an explicit authorized user command after approval, never a scan of
scheduled rows or an automatic approval-completion side effect. In one transaction:

1. Check authoring control and user scheduling permission with fresh workspace and
   resource scope. Verify selected channel belongs to the parent and workspace.
2. Lock and reload the authoritative content, channel, and approval records.
   Require parent status `approved` or `scheduled`. `draft`, `in_review`,
   `published`, `cancelled`, and `archived` are ineligible.
3. Require a non-null channel UTC instant and validated IANA authoring timezone;
   verify expected revision and generation supplied for concurrency control.
4. Require `approved_revision == content_revision`. Use
   `approvals.find_conflicting_or_resolved_request` scoped to workspace,
   `marketing_content_item`, content ID, and that revision. Require the returned
   completed request to have status `approved` and no invalidation decision.
   Record its exact ID and revision on the job. Do not trust parent status,
   `approved_at`, a client-supplied approval ID, or denormalized approval fields
   alone. A contradictory non-null parent request pointer must be repaired before
   activation, not silently used as a different approval authority.
5. Verify no occupying job and no prior handoff for this revision/generation;
   perform the active-slot/idempotency checks and insert the immutable snapshot.
6. Update compatibility projections and insert sanitized realtime events in the
   same transaction, then commit once.

Approval evidence must include invalidation decisions: currently
`approval_service.record_current_approval_invalidated` appends an `invalidated`
decision without changing the request's `approved` status. The existing
`_has_completed_approval_for_current_revision` helper alone is therefore not the
entire future eligibility check. The pure contract accepts repository-derived
`ApprovalEvidence`; it must never accept that evidence from an API caller.

The [executable activation service](scheduling-activation.md) requires shared
automatic eligibility, including enabled execution, a configured durable receiver
and an available automatic destination. It rejects missing and manual-only
destinations. The earlier optional planning-only activation mode is not implemented;
parent/channel authoring intent remains the planning representation. Activation
does not dispatch, and acceptance must independently revalidate eligibility. New
activation rejects instants already older than the configured lateness window
with `missed_schedule_window`; no executable job is created. A future-dated
activation stays pending until due. Legacy rows require explicit selection,
timezone confirmation, and this same eligibility check; there is no backfill
activation. A missed legacy time must be rescheduled, not given a window bypass.

At claim **and again immediately before acceptance**, check revision, exact
approval evidence/ID, parent eligibility, channel ownership/existence, snapshot
equality/generation, execution controls, due window, destination readiness, and
claim fence where applicable. Data loaded before a lock is not authoritative.

## 4. Complete lifecycle transition table

All state edges are below. All other edges are illegal. An idempotent command
replay returns its recorded result without making another edge or history event.
`none` is absence of a job, not a stored state.

| From                              | To            | Operation / authorized actor                                                       | Required guard                                                                                                                                                |
| --------------------------------- | ------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| none                              | pending       | activate / user scheduling command                                                 | Complete activation eligibility and unique active slot.                                                                                                       |
| pending                           | claimed       | claim / trusted worker                                                             | Execution enabled, receiver configured, due within window, valid approval/snapshot/destination; allocate owner, lease and new fence.                          |
| pending                           | blocked       | block / trusted validator                                                          | Due work fails an execution guard; persist stable reason and diagnostics.                                                                                     |
| claimed                           | handed_off    | accept_delivery / trusted worker through Delivery port                             | Current claim fence/lease and all guards; inbox acceptance and job transition commit atomically.                                                              |
| claimed                           | blocked       | block / trusted worker or recovery coordinator                                     | Validation fails before acceptance; no committed delivery receipt. Fence the old claim.                                                                       |
| pending, claimed, blocked         | cancelled     | cancel / permitted user; content/channel removal or ineligible lifecycle operation | Acquire coordination locks before acceptance; record cancellation reason and fence claim.                                                                     |
| pending, claimed, blocked         | superseded    | supersede / material-edit or replacement operation                                 | Revision/intent replaced before acceptance; record old snapshot and supersession operation; fence claim.                                                      |
| blocked                           | pending       | revalidate / explicit permitted user command                                       | Exact unchanged snapshot and approval still valid, blocker resolved, all execution checks pass, time within window; no automatic unblocking.                  |
| claimed                           | pending       | recover_claim / trusted recovery coordinator                                       | Lease expired by DB clock, no accepted inbox record, old fence revoked, revision/approval/snapshot/time still valid. Otherwise block with the failing reason. |
| handed_off, cancelled, superseded | No transition | No actor                                                                           | Terminal: no outgoing transitions.                                                                                                                            |

The final row declares no transitions; it does not permit deletion. Updating a
blocked job's diagnostic reasons after another failed validation is a metadata
update with its own audit entry, not a new state edge or successful revalidation.
Terminal records cannot receive these updates. `blocked`
requires a non-null reason. Revalidation cannot cure a stale revision, stale
approval, changed generation, or missed window by editing the job. Supersede and
activate a successor after the appropriate fresh approval. Manual-only jobs stay
blocked in this initial contract. Changing them to an automatic destination is a
material edit. Unavailable receiver configuration keeps pending work pending with
an execution-disabled projection; a validator that encounters it during an
attempt may instead block with `missing_durable_delivery_receiver`.

## 5. Invalidation, cancellation, and rescheduling

Any material edit invokes revision invalidation and job invalidation as one unit
of work. Preserve the current material field rules, including channel time,
destination, placement, copy, assets, metadata, parent time, campaign, and artist.
Increment revision once per logical edit. Supersede every occupying job on the
parent's old revision, including jobs on otherwise unchanged sibling channels;
jobs on explicitly removed channels are cancelled instead, in that same transaction.
Return approved/scheduled/in-review parents to draft using existing invalidation
semantics. Capture the old approval ID in history even if parent pointers clear.
An independent approval revocation without a material edit blocks occupying jobs
with `stale_approval`; the stale authorization cannot be revalidated as current.
Parent cancellation/archive/return-to-draft explicitly cancels occupying jobs.

Rescheduling is an edit of channel intent, incrementing generation and parent
revision, invalidating approval, and superseding old occupying jobs. The old job's
time is never moved. There is no successor executable job until the new revision
is approved and explicitly activated. Record the supersession operation even
when no successor exists yet; link the later successor to its predecessor and
root lineage. Cancellation alone does not edit content or invalidate approval.
Reactivation after cancellation can reuse still-current approval and intent,
within the window, but creates a new job with explicit lineage and operation ID.

For claimed work, cancellation/invalidation succeeds only if its database
transaction wins before durable acceptance. If acceptance has committed, the job
stays `handed_off`; return a structured `already_handed_off` cancellation outcome.
A later permitted content edit can invalidate future work but cannot retract the
accepted immutable payload. Preserve that handoff and surface this outcome to the
editor. A downstream recall belongs to Delivery. For mixed channel states, report
each result; never claim all work was cancelled when one channel was handed off.

## 6. Locking and transaction boundaries

Initial architecture decision: a Delivery-owned durable inbox in the **same
database transaction** as Scheduling acceptance. There is no remote receiver
protocol in this rollout. A remote acknowledgement alone cannot settle the
cancellation race and must not be wired to this port without a new coordinated
acceptance design.

Use one caller-owned transaction and a consistent order: execution control rows
(shared read locks for execution, exclusive locks for control changes),
parent rows sorted by ID,
channel rows sorted by ID, approval requests/stages sorted by ID, job rows sorted
by ID, destination rows sorted by ID, then Delivery inbox rows. Re-read under
lock. Approval mutations must adopt the parent-first order too; the existing
approval request lock helper is not sufficient coordination by itself. Lock
campaign/artist scope sources after parents and before channels when their values
determine effective artist context; context writers must use the same order.

All activation, material edits, approval revocation, parent lifecycle changes,
channel removal, cancellation, claim recovery, and handoff operations serialize
through the parent lock. Use row locks and conditional writes with expected
state/version/fence; no process-local mutex. Database uniqueness is the final
active-job conflict guard. Candidate due selection is read-only and indexed;
then acquire locks in the above order with nonblocking/skip-locked behavior and
revalidate. Do not first lock a job and then its parent. Claims are bounded leases
with monotonic fencing, not authorization. Lease duration is configuration.

Claim commits a short transaction before doing subsequent local preparation.
Acceptance acquires fresh locks, checks owner/fence/unexpired lease and all guards,
inserts/deduplicates the inbox, writes receipt plus `handed_off`, updates the
compatibility projection, and inserts realtime/history events, then commits once.
There is no provider/network I/O under these locks. Destination health and scope
mutations serialize through their own rows; any change committed before the
acceptance check is observed. Health changes after acceptance belong to Delivery.

Cancellation taking the job lock first via the common order commits a terminal
state and a new fence; the worker can no longer accept. Acceptance winning first
commits the inbox and `handed_off` together; cancellation observes that terminal
state. A crash before commit rolls back both; a crash after commit leaves both.
On an ambiguous commit result, reload durable state by job/idempotency key before
retrying. Never assume failure and create another job. An inbox/job inconsistency
is a contract violation requiring reconciliation, not automatic resend.

Required atomic units:

| Operation                      | Must commit or roll back together                                                                                                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Activate                       | Approval eligibility, revision/generation verification, active conflict check, snapshot insertion, activation idempotency, compatibility projection, history and realtime insertion.             |
| Edit/reschedule/replace        | Source changes, revision/generation increments, approval invalidation audit, all affected job cancellations/supersessions and lineage, compatibility projection, history and realtime insertion. |
| Cancel/lifecycle/revoke        | Authorization and eligibility recheck, coordinated state/fence changes, applicable approval changes, projection, history and realtime insertion.                                                 |
| Claim/recover/block/revalidate | Guard checks, state/fence/lease/reason updates, projection, history and realtime insertion.                                                                                                      |
| Accept                         | All eligibility checks, durable inbox deduplication/payload acceptance, receipt, handed_off state, projection, history and realtime insertion.                                                   |

Current internally committing services must be refactored into caller-owned
unit-of-work helpers before composition:

- `marketing_content_service.create_content_item`, `update_content_item`,
  `update_content_item_with_channels`, `replace_channels`, `update_channel`, and
  `transition_status`; `archive_content_item` delegates to `transition_status`.
  Approval paths in `transition_status` also call committing approval services.
- `approval_service.submit_resource_for_approval`, `assign_stage_reviewer`,
  `_human_stage_decision` (through `approve_request`, `request_changes`,
  `reject_request`), `_system_or_submitter_resolution` (through `cancel_request`,
  `invalidate_request`), and `resubmit_resource`.

`record_current_approval_invalidated`, content repository writes, and
`RealtimePublisher.publish` do not commit internally; preserve that property while
adding locking. Flush is permitted. Do not wrap a committing service in
`session.begin()` and assume atomicity. Never dispatch realtime before commit.

## 7. Destination policy and stable blocked reasons

At due time use `social_account_service.resolve_destinations` through a trusted
execution adapter, with the job's workspace, the channel's provider, exact
requested connection ID, `desired_capability="content_publish"`, and effective
artist profile (`item.artist_id` or campaign artist, as current validation does).
Verify context still matches the snapshot. Never choose another available account
as fallback. The resolver's current public authorization entrypoint must gain a
proper internal authority path before worker use; passing `actor=None` is forbidden.
Use its readiness projection only, with no credentials, health refresh, or provider
API calls. Planning retains existing permissive health/manual destination rules.

| Stable scheduling reason            | Source/meaning                                                                                                         |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `connection_unavailable`            | `NO_CONNECTION`, `DISCONNECTED`, `CONNECTION_ERROR`, or no usable requested account after other specific reasons.      |
| `reconnect_required`                | Resolver `RECONNECT_REQUIRED` (includes pending connection status today).                                              |
| `capability_unavailable`            | `MISSING_CAPABILITY`, or automatic publication unavailable without manual-only capability.                             |
| `destination_mismatch`              | `PROVIDER_MISMATCH`, `WRONG_ARTIST`, `WRONG_WORKSPACE`, changed destination ID/context, or channel ownership mismatch. |
| `manual_delivery_required`          | Requested destination requires assisted publication; initial execution does not create manual tasks.                   |
| `stale_content_revision`            | Job's approved content revision differs from parent revision.                                                          |
| `stale_approval`                    | Projection/evidence/request identity mismatch, non-completed approval, or invalidation decision.                       |
| `changed_schedule_generation`       | Generation differs or channel time differs from immutable job time, even if generation was incorrectly unchanged.      |
| `missing_durable_delivery_receiver` | Missing/no-op receiver, or configured adapter cannot provide transactional acceptance.                                 |
| `missed_schedule_window`            | Due instant older than effective configured lateness window.                                                           |
| `ineligible_parent_state`           | Parent is outside approved/scheduled.                                                                                  |
| `missing_schedule_intent`           | Channel schedule removed or absent.                                                                                    |
| `handoff_contract_violation`        | Receipt/key/fingerprint mismatch or inconsistent durable inbox/job state.                                              |

Collect sanitized reason codes for diagnostics; choose a primary deterministically:
ownership/context mismatch, stale revision, stale approval, parent state, missing
intent, changed generation, missed window, receiver unavailable, then destination
health/capability. Within destination reasons use mismatch, connection unavailable,
reconnect, manual-only, capability. Manual-only takes precedence over the expected
missing `content_publish` result, but not over connection health errors. Do not
expose cross-workspace account details in diagnostics. Successful material-edit
coordination supersedes jobs; stale blocked reasons are defensive guards for
out-of-band drift or concurrent observations, not a substitute for invalidation.

## 8. Durable handoff contract

`PublishingDeliveryAcceptancePort.accept(session, request)` accepts a
provider-neutral envelope under the caller's locked transaction. The receiver
must persist a Delivery-owned inbox payload and return `DurableAccepted` with a
matching `DeliveryAcceptanceReceipt`, or return `RetryableUnavailable` or
`TerminalRejected` without accepting work. Scheduling sets `handed_off` only for
`DurableAccepted` in that transaction;
durability is confirmed only by successful outer commit. The receiver must not
commit independently. Receipt construction or a successful method return alone
is not evidence of durable acceptance.

The envelope contains snapshot IDs/revision/approval/generation/time, job ID,
destination ID, effective artist profile, IANA authoring timezone, schema version,
canonical payload bytes and fingerprint, execution mode and stable correlation
UUID. Payload v1 is canonical JSON with resolved
caption (channel override before parent), approved digest asset references with
embedded verified immutable bytes,
structured hashtags, channel/placement, and sanitized delivery-relevant metadata.
Use UTF-8, sorted keys, compact separators, no NaN, and SHA-256 of a versioned
canonical envelope including all routing, authorization and payload fields except
the fingerprint itself. The [v1 policy and fixtures](scheduling-delivery-handoff.md)
define the encoding and asset verification required of a future Delivery adapter.
Mutable asset references must be versioned or copied into immutable Delivery
storage before acceptance; a bare mutable URL is insufficient.
The receiver rechecks fingerprint binding. Credentials and provider result fields
are prohibited. The DTO's bytes do not themselves validate payload schema.

Idempotency key: `labelos:scheduling:v1:{workspace_id}:{job_id}`. It stays fixed
across claims, lease recovery, transaction retries and duplicate calls. Unique
inbox key plus equal fingerprint returns the same receipt/delivery request ID;
the same key with different content is a hard conflict, never an overwrite. A
receipt includes delivery request ID, key, and fingerprint. Scheduler verifies
these bindings before commit. A contract violation rolls back acceptance and is
recorded as blocked in a new guarded transaction if no acceptance committed.

A fake may model acceptance in contract tests but cannot certify production
durability. A no-op development receiver returns `RetryableUnavailable`, never
manufactures success. The composer also translates legacy
`DurableDeliveryReceiverUnavailable` exceptions to nonacceptance. Timeout or unknown
commit outcome requires durable readback; an explicit unavailable receiver blocks
or leaves work pending. No delivery inbox exists today, so execution remains off.
Provider retry/backoff begins only inside Delivery after acceptance; Scheduling
only retries database coordination, using the original key and current fence.

## 9. Worker trust model

User commands and internal execution are separate authorization paths. Future
activation, cancellation, and revalidation require a human workspace actor with a
dedicated `marketing.content.schedule` capability plus resource scope; content
edits still require `marketing.content.edit`. Add the dedicated capability and
grants before those endpoints ship. Existing parent status changes retain their
current edit permission and AI-agent restrictions. They do not grant execution.

The worker uses a dedicated deployment workload identity mapped server-side to
`scheduling.execute`, with an allowlisted workspace scope and instance ID for
audit. It is neither a user nor an AI agent. Validate identity, audience, lifetime
and scope at the trusted boundary; never deserialize worker authority from user
JSON, use `actor=None`, or impersonate an approving user. Recheck scope for every
job. Internal resolver/approval adapters accept only this authenticated context;
the acceptance port is called behind that boundary, not exposed as a public API.
Minimum database privileges cover scheduling coordination, necessary content/
approval/destination reads and Delivery inbox acceptance. No credential-store,
provider API, approval-granting, or arbitrary content-edit authority. Null user
fields in a realtime envelope are presentation only, never worker authentication;
transition audit records always retain the workload principal and instance.

## 10. UTC, IANA timezone, DST, and lateness

Persist instants in UTC and the explicitly selected IANA authoring timezone on
channel intent and snapshots. Require a local wall-time, timezone, and explicit
offset/fold choice when ambiguous; the server validates the zone and round-trips
the chosen instant. Reject nonexistent DST times, ambiguous times without a
choice, unknown zones, naive instants, and offsets inconsistent with the zone.
Do not silently shift a nonexistent time or choose the first ambiguous occurrence.
An existing approved instant never drifts after timezone-database updates. A
timezone/time edit is material and requires fresh approval. Store the authoring
wall-time and chosen offset as audit context alongside the canonical UTC instant.

Before execution, replace `marketing-workspace.tsx`'s `formatDateTimeInput`
(string slicing) and `dateTimeInputToIso` (`new Date(value).toISOString()`) with
explicit-zone parsing/display and backend DST validation. Existing calendar
display utilities do not establish safe authoring. Legacy zone cannot be inferred
from the browser: require confirmation; changing legacy intent follows approval
invalidation. Regression cases must include New York 2026-03-08 02:30
(nonexistent), 2026-11-01 01:30 (two instants), a non-hour offset zone, and a
browser timezone different from the selected authoring timezone.

Deployment configuration `scheduling_lateness_window_seconds` is nonnegative and
required before activation or execution. Recommended initial deployment value: **300 seconds**;
the domain has no baked-in duration or default. Use one effective deployment value
and record its version/value with decisions; changing it never automatically
reactivates blocked/legacy work. `now` comes from the database clock at claim and
acceptance, not a browser or worker host clock.

- `scheduled_for > now`: future, cannot claim early.
- `now - window <= scheduled_for <= now`: claimable, both boundaries inclusive.
- `scheduled_for < now - window`: block `missed_schedule_window`.

A lease does not extend the window: work that ages out before acceptance blocks.
A zero window permits only exactly-due work. Execution downtime longer than the
window does not authorize a backlog burst. Expired jobs require explicit human
rescheduling/fresh approval; an unchanged blocked job can only be explicitly
revalidated if its original instant is within the effective window. There is no
legacy bypass and no startup scan that creates executable jobs from scheduled rows.

## 11. Parent status, calendars, and notification projections

Keep `MarketingContentItemStatus` unchanged. Existing parent schedule is planning;
parent status is a compatibility summary and is never used as a per-channel queue.
Channel views expose job ID/state, intended time/zone, blocked reason, lineage and
whether execution is enabled. `not_activated` is a read label, not a job state.

Activation may project an eligible approved parent to `scheduled`; mixed channel
states still show `scheduled`. Job transitions alone do not roll the parent back
or mark it published. Cancellation/blocked/handed-off channel states remain visible
separately. Explicit existing parent lifecycle commands and material invalidation
retain ownership of parent status. A stale `scheduled` compatibility label never
bypasses approval checks. This avoids one channel completing or failing overwriting
another channel's state. Delivery must define any future publication aggregate.

Both calendars produce one intent event per channel. Preserve Campaign Calendar's
stable key `marketing_content_channel:{channel_id}:scheduled` and enrich that event
with the current occupying job, or latest terminal job when none occupies the slot.
Join by workspace and stable channel ID; do not concatenate legacy and job event
streams. The event time remains channel authoring intent; history is a separate
detail view. If a terminal job describes old intent, show it as prior history, not
as the current intent's execution state. Removed channel/job history does not
create a current calendar event. Parent planning uses its separate existing key
`marketing_content:{content_id}:scheduled`, labelled as parent planning; it never
duplicates a channel job event. Calendar reads use existing visibility rules and
perform no activation or state writes. Realtime notifications invalidate these
read projections and contain sanitized identifiers/state, not delivery payloads.

## 12. Feature controls and rollout

These names describe controls to implement later; this change does not install flags.

| Control                        | Policy                                                                                                                                                                         |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `scheduling_authoring_enabled` | Gates new schedule-authoring/activation/revalidation user flows; initial rollout on after authoring prerequisites. Inspection and cancellation remain available even when off. |
| `scheduling_execution_enabled` | Default off; gates both claim and acceptance. Turning off stops new handoffs once observed under the coordination transaction.                                                 |
| `delivery_receiver_configured` | Server-derived readiness for a real transactional adapter, never a client toggle. Must be true alongside execution enabled.                                                    |

Authoring and execution are independent: disabling authoring need not stop
already-activated work. Emergency stop uses execution control. Changes to execution
control must serialize with acceptance via a database-backed control/version check
in the transaction; an in-memory environment read cannot promise an atomic stop.
Already committed handoffs belong to Delivery. Disabling execution leaves pending
jobs pending; an unaccepted claimed job may be released through fenced lease
recovery, or blocked if already stale/missed. No flag activates historical rows.

1. Contracts only (this change): no persistence or execution behavior.
2. Identity, unit-of-work, authorization and timezone prerequisites with execution
   off; preserve current authoring until new safe authoring flows are available.
3. Future job persistence and explicit authoring APIs: authoring on, execution off,
   receiver absent. Users create and inspect pending schedules. No legacy backfill.
4. Transactional Delivery inbox/adapter and trust boundary verified in tests;
   receiver configured, execution still off. Simulate/read projected readiness.
5. Enable execution for an explicit workspace allowlist after race, DST, rollback,
   isolation and idempotency tests pass. Observe blocked counts, claim age, lateness,
   and acceptance outcomes. Widen only deliberately. Roll back by turning execution
   off; preserve all history and downstream accepted work.

## 13. Exact next implementation sequence and acceptance gates

Each step is a separate reviewable follow-up; none is implemented here.

1. **Stable identity first:** reconcile channel writes in
   `repositories/marketing_content.py`, channel service methods, API request DTOs,
   and web editor rows. Tests: no-op/reorder retains ID and approval, explicit
   replacement retains old history, duplicate/foreign IDs rejected. Introduce
   retirement semantics before executable FKs; do not delete historical targets.
2. **Unit of work and authority:** refactor the committing methods listed above,
   enforce common lock order, add dedicated scheduling user capability and trusted
   execution context/internal resolver path. Tests: rollback includes approval,
   content, projection and events; anonymous/AI/foreign-workspace execution denied.
3. **Safe authoring:** channel IANA zone/generation metadata, UTC/DST server
   validation, zone-aware editor conversion, explicit legacy confirmation.
   Tests: DST cases above and every material field invalidates parent approval.
4. **Future persistence:** only after 1–3, propose a job/history migration with
   stable channel FKs, active-slot uniqueness, due index, lineage, operation
   idempotency, state/reason/receipt constraints, and fenced lease fields. Leave
   historical schedules unactivated. Verify upgrade/rollback and no implicit jobs.
5. **Authoring application service/API:** explicit channel activation, cancellation,
   rescheduling and revalidation using one transaction. Add calendar enrichment
   with stable keys. Tests: stale approvals, invalidation decisions, sibling job
   supersession, duplicate requests, active conflicts, legacy refusal and no duplicate
   calendar events. Execution remains disabled.
6. **Delivery acceptance:** Delivery-owned inbox migration and transactional adapter,
   immutable payload encoding/assets and conformance tests. Verify same key/same
   payload deduplicates; different payload fails; unavailable/no-op receiver fails;
   injected failure rolls back both inbox and job. No provider execution needed to
   validate Scheduling's acceptance boundary.
7. **Worker and recovery:** implement DB-time due scan, scoped workload identity,
   feature control coordination, claim leases/fences, final resolver/approval checks,
   and acceptance. PostgreSQL multi-session tests must prove cancellation wins,
   acceptance wins, stale worker cannot hand off after recovery, concurrent
   reschedule/approval revoke prevents stale work, lost acknowledgement is deduped,
   destination/control changes serialize, and aging out before handoff blocks.
8. **Rollout and observability:** structured workload audit, reason metrics,
   calendar/UI inspection and explicit missed-work recovery; execute the allowlist
   rollout above. Do not enable until the receiver and all prerequisite tests pass.

## 14. Verification and remaining decisions

Focused tests in
[`test_scheduling_contracts.py`](../../apps/api/tests/test_scheduling_contracts.py)
exercise all state/operation combinations, approval identity/scope/invalidation,
snapshot drift, inclusive configurable lateness, independent feature controls,
and receipt binding. They do not prove database races, authentication, DST parsing,
or durable delivery; those require the implementation gates above. No production
service imports or invokes these contracts in this change.

Files changed: this architecture document, `scheduling/__init__.py` and
`scheduling/contracts.py` under `apps/api/src/labelos_api`,
`apps/api/tests/test_scheduling_contracts.py`, and the adjacent
`assisted-publishing-handoff-contract.md` and `social-account-connections.md`
(aligned manual-task ownership and linked this contract).

Validation on 2026-09-14:

- From `apps/api`: `python -m pytest tests/test_scheduling_contracts.py -q`:
  **103 passed**, no warnings.
- From `apps/api`: `python -m ruff check src/labelos_api/scheduling tests/test_scheduling_contracts.py`:
  passed.
- From repository root: `pnpm.cmd exec pyright apps/api/src/labelos_api/scheduling`:
  zero errors/warnings.
- Black formatting verified through `black.format_str` with Python 3.12 target
  and line length 88; the local Black CLI stalled and was stopped.
- Prettier checked the three changed Markdown files; `git diff --check` passed.

No migrations, runtime services, provider integrations, or parent enum changed.

Resolved here: executable unit, approval ownership, source of truth, initial
eligible states, all transitions, active-slot definition, atomic acceptance model,
manual delivery blocking, lineage, parent/calendar semantics, historical opt-in,
and fail-closed execution. There is no unresolved policy exception allowing early
execution.

Remaining implementation/deployment choices (must be settled before their gate):

- Delivery normalization and immutable assets (step 6) are resolved for the
  [v1 snapshot boundary](scheduling-delivery-handoff.md): approved digest references
  plus embedded verified bytes. Production inbox/adapter certification remains a
  deployment gate; no arbitrary mutable references are allowed.
- Workload identity issuer/audience and deployment provisioning, least-privilege
  role wiring (steps 2/7); the trusted boundary is mandatory regardless of issuer.
- Operating defaults are resolved in the [rollout policy](scheduling-reliability.md):
  120-second lease, 25-job batches, minute sweeps, 300-second lateness tolerance
  for existing jobs, and three internal availability attempts. New activations
  must be future-dated; deployment timing overrides remain explicit.
- History is retained indefinitely in PostgreSQL, without automatic archival or
  deletion. Physical channel tombstones remain a future gate; referenced channel
  removal currently fails and rolls back rather than deleting history.
- Product timing of a future manual Delivery workflow or remote acceptance design;
  neither is part of this initial execution contract.
