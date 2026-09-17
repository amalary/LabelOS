# Publishing Stage 8: retry engine and failure classification

Production execution now uses the independent
[Stage 9 Publishing worker](publishing-worker.md), which adds database-clock leases,
fencing, heartbeats and conservative recovery around this retry policy.

Stage 8 adds normalized failure categories, durable eligibility, and a bounded
`DeliveryOrchestrator.retry_due()` sweep. HTTP codes and provider error bodies are
interpreted only by adapters. A retry always creates a new `PublicationAttempt`
and start/result transitions, preserving the publication, approved envelope,
destination binding, and provider idempotency key.

## Classification and policy

| Failure category        | Decision                           | Recovery                                                                           |
| ----------------------- | ---------------------------------- | ---------------------------------------------------------------------------------- |
| `transient_network`     | Automatic                          | Only when the adapter proves final nonpublication, such as a timeout before upload |
| `provider_unavailable`  | Automatic                          | Includes 5xx before any publication write                                          |
| `rate_limited`          | Automatic or provider delay        | Use safely parsed Retry-After as a minimum wait                                    |
| `authentication`        | Blocked pending reconnection       | Restore revoked, missing, or expired credentials                                   |
| `authorization`         | Blocked pending reconnection       | Reconnect with required grants/scopes                                              |
| `invalid_content_media` | Permanent for this approved intent | Correct content/media and obtain a new approved intent                             |
| `unsupported_operation` | Permanent for this intent          | Select a supported operation/destination                                           |
| `ambiguous_outcome`     | Reconciliation required            | Prove final publication or final nonpublication; never blindly publish again       |
| `permanent_rejection`   | Permanent for this intent          | Review the provider rejection before creating corrected work                       |
| `internal_failure`      | Manual action                      | Repair the LabelOS failure before authorizing recovery                             |

Every nonautomatic decision is a manual-action candidate, including exhausted
budgets. The existing lifecycle `retryable_failure` records a definite absence
that is potentially recoverable. **It is not permission to retry.** Credential,
scope, and internal failures can remain in that lifecycle state with a blocking
`retry_disposition` and no eligible time. Permanent failures remain terminal;
ambiguous outcomes remain `manual_action_required`. Neither a health update nor
queue redelivery releases a blocked publication.

Policy version 1 is fixed and persisted:

- Five total attempts, including the initial attempt and local preflight failures.
- A 24-hour budget from the first attempt start, never reset by reconciliation,
  process restart, another command ID, or another failure. No retry may start at
  or after the deadline; an already running attempt still records its real outcome.
- Equal-jitter exponential delay: `cap = min(1800, 30 * 2^(attempt_number - 1))`
  seconds; choose uniformly between `cap/2` and `cap`. The four ordinary retry
  windows are 15–30, 30–60, 60–120, and 120–240 seconds.
- A normalized provider delay raises that minimum; jitter never schedules before
  it. A delay that reaches/exceeds the deadline produces `exhausted` with no next
  eligible time. Hitting attempt five also persists `exhausted`.
- A waiting publication whose deadline passes is excluded from selection and
  execution even if its original scheduled time remains in history. Its persisted
  deadline makes expiry independently computable without a background mutation.

The YouTube adapter accepts bounded ASCII delta seconds and timezone-aware HTTP
dates in Retry-After (0–604800 seconds). Malformed, non-ASCII, naive, and out-of-range
hints are discarded. The hint is consulted only after safe failure normalization.
Structured final rate/quota, authentication, scope, and invalid-media rejections
can establish noncreation after upload begins. An unstructured 429, 5xx, lost
response, or timeout after upload starts remains ambiguous. Unhandled adapter
exceptions and malformed post-write results also require reconciliation.

## Persistence and concurrency

Migration `202609170100` adds failure category, disposition, policy version, next
retry time, and deadline to the publication projection and append-only transition
history. Transitions additionally retain the bounded provider delay. Observation,
retry decision, projection, and realtime outbox commit atomically. Raw exception
messages, response bodies, headers, and credentials are not stored.

`due_retries()` selects workspace-scoped candidates through a due-time index.
`retry_due()` performs one bounded sweep (default 100; maximum 1000), with no sleep
or recursive retry loop. The failure transition version determines a stable
execution command UUID. A restarted host derives the same command; existing
execution uniqueness and version checks reject replay and competing commands.

Before every retry, normal source/job/destination/publication locking rechecks
content approval, cancellation, account health and identity. Both the repository
and database attempt-insert guard enforce eligibility, deadline, and attempt limit.
The start is committed before adapter I/O. Cancellation while waiting clears the
projection's retry schedule and appends a cancellation fact, retaining the earlier
failed attempt and scheduled eligibility in history.

Legacy rows receive nullable fields without rewriting immutable history. A legacy
failure with no policy/eligible time cannot automatically execute. Successful,
cancelled, and executing projections have no active retry schedule. PostgreSQL's
deferred projection guard also checks that retry fields match the latest journal
entry. Downgrade restores the previous guards before removing the new fields.

## Verification and Stage 9 handoff

`test_publication_retries.py` exercises all ten classifications, exact jitter
boundaries, provider delay floors and HTTP dates, 429/5xx safety, persisted budgets,
restart and success after retry, tenant isolation, deadline expiry, cancellation,
and direct-SQL early-attempt rejection. Existing provider tests exercise actual
mocked YouTube timeouts, revoked credentials, reduced scopes, and ambiguous writes.
Existing PostgreSQL suites cover concurrent attempt commands, rollback, immutable
history, and migration upgrade/downgrade. Clocks and jitter inputs replace waiting;
no tests need real provider credentials or wall-clock retry sleeps.

Stage 9 can consume the persisted classifications, eligible times, deadlines, and
bounded sweep. Production host cadence and operator/reconnection recovery UI are
not enabled by this stage. A recovery workflow must explicitly validate restored
account identity, grants, approved content, absence evidence, and the existing
budget before releasing blocked work; it must not merely reset status or attempt
counts. YouTube still has no authoritative idempotency-key reconciliation lookup,
so uncertain uploads require operator investigation. Apply the migration before
running the updated delivery host.

Verified locally on 2026-09-16 with an isolated PostgreSQL 17 cluster and SQLite:
605 publishing, scheduling-handoff, and database regression tests passed. After
final adapter classification refinement, all 178 provider/retry tests passed again.
API Ruff, configured Pyright, Black formatting, and `git diff --check` passed. The
broader whole-API run was stopped in favor of these affected suites; this report
does not claim a completed whole-API run.
