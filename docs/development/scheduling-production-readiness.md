# Scheduling Engine production-readiness audit

Audit date: 2026-09-16. Baseline: `3bdb43a`, plus the scoped fixes listed below.
Verification used Windows, Python 3.14, PostgreSQL 17.5 on an isolated loopback
instance, and the repository's installed JavaScript dependencies. PostgreSQL tests
used disposable schemas and separate connections. No production data, IAM,
deployment controls, or provider accounts were changed.

## 1. Overall readiness

**Conditional pass for Scheduling coordination; no-go for live publishing.**
The engine is suitable as the foundation for implementing Publishing Delivery.
Execution must remain disabled until a real transactional receiver is certified.
The default receiver deliberately refuses acceptance, and production activation
also fails closed without receiver readiness and both execution controls.

This is not an unconditional application production sign-off: the dependency
audit reports critical/high advisories, and a full database downgrade to base
exposes an unrelated Analytics migration re-upgrade defect. Neither was changed
because this audit only authorizes Scheduling fixes.

## 2. Architecture findings

One immutable job targets one stable channel ID and one approved parent revision.
Channel time is executable intent; parent time and parent `scheduled` status are
planning only. Explicit activation is the only job-creation path. Realtime is a
transactional notification outbox, not the worker queue. Calendars are read projections.

Scheduling owns activation, cancellation, supersession, claims, fencing, recovery,
and durable handoff. `handed_off` means accepted by Delivery, not published.

**Confirmed excluded from Scheduling:** provider publishing API calls, media
uploads, credential retrieval/refresh, provider retries/backoff, rate-limit
handling, manual publishing tasks, provider post IDs/URLs, and publication history.
The worker's Google JWKS fetch authenticates its caller; it is not provider delivery.
Scheduling does retain its own transition/receipt history. Existing content
publication fields and other legacy product workflows are separate from this engine.

## 3. Database and migration findings

- Workspace/content/channel/destination/approval composite foreign keys constrain
  snapshot ownership. Unique activation operation IDs, idempotency keys, active
  channel slots, accepted intents, and handoff receipts prevent duplicate work.
- Immutable snapshot/terminal-row triggers and append-only transition triggers
  preserve fences and history. State/lease/receipt constraints reject invalid rows.
- UTC instants and explicit IANA context are retained. Due and workspace-list
  indexes exist; PostgreSQL tests verify the due index and bounded batch behavior.
- Single Alembic head: **`202609152100`**.
- Fresh full upgrade to head: passed. Full downgrade to base: passed. Full
  re-upgrade: **failed** at Analytics revision `202608291600`, because
  `analytics_metric_value_type` remains after downgrade and is created again.
  This is outside Scheduling. Do not describe whole-repository rollback/re-upgrade
  as certified.
- On a separate database, the complete Scheduling range
  `202609061800 -> 202609152100 -> 202609061800 -> 202609152100` passed.
  Migration regressions also preserve legacy channel intent/publication data and
  verify that migration creates zero Scheduling jobs or enabled workspace controls.

## 4. Service and transaction findings

The audit found and fixed an unwired material-edit invalidation hook. Previously,
an edit cleared approval but left its active jobs occupying channel slots until
later defensive worker validation. Immediate edit/reapprove/replacement could fail.

Material edits now retire every active sibling job under the existing parent lock,
including pending, blocked, and claimed jobs. Claims lose their fence, and audit
plus outbox writes share the content transaction. Author identity/kind is retained,
including AI authoring; this does not grant AI activation authority. Rollback restores
content, approval, jobs, and transition events together. Terminal accepted/cancelled
history is preserved. Physical removal of referenced channels remains prohibited
by history foreign keys; failed removal rolls back rather than erasing history.

Human activation and replacement require current revision/generation guards,
completed approval evidence, authorized scope, compatible destination, future
intent, trusted feature controls, and a durable receiver. Replays return existing
results without creating new jobs. Replacement after cancellation or supersession
requires a material edit and new approval, and preserves predecessor/root lineage.

## 5. API and authorization findings

Public commands require authenticated humans with `marketing.content.schedule`
and workspace/campaign authorization. Reads use content-view/resource checks.
Anonymous, AI, insufficient-capability, foreign-workspace, and foreign-resource
commands are rejected. Strict DTOs do not accept worker authority or execution flags.
UUID idempotency headers and workspace operation locks coordinate command replay.

The audit fixed an eligibility projection inconsistency: recently overdue intent
inside the worker lateness window could display as eligible even though activation
rejected it. New-activation eligibility now rejects every instant at or before
database time. Worker recovery/revalidation retains its separate lateness policy.

Inspection and cancellation remain available with authoring disabled. Claim and
execution routes are absent from the public application. Safe API views exclude
lease identities, payloads, credential metadata, and raw exception details.

## 6. Worker and concurrency findings

Private worker authentication validates RS256 signature, trusted Google issuer,
exact audience, expiry/issued-at, pinned service-account subject/email, and verified
email. Scope and limits come from deployment, not JSON or Scheduler headers.
Local CLI execution requires explicit development mode and a loopback database.

PostgreSQL parent/source/job locking, `SKIP LOCKED`, database wall-clock checks,
leases, and monotonic fencing prevent simultaneous valid claims and stale acceptance.
Future, terminal, cancelled, disabled, foreign-workspace, and unactivated legacy
work cannot be claimed. Destination and durable execution-control locks serialize
acceptance with disconnect/shutdown. Due processors use bounded recovery and claim
budgets, with per-job transactions and partial-failure isolation.

The test-only Delivery inbox has unique keys and fingerprint conflict detection.
Inbox acceptance, Scheduling receipt/state, audit, and outbox commit atomically.
Tests cover a crash before the job update (everything rolls back), lost commit
acknowledgement (same durable receipt is read back), concurrent replay, lease
expiry during acceptance, and stale-worker rejection. These certify the Scheduling
boundary against a transactional test receiver, not an absent production adapter.

Only explicit known handoff unavailability receives bounded coordination retries:
three automatic attempts recorded durably. This is not provider retry handling.

## 7. Frontend and calendar findings

Frontend tests cover stable channel editing, exact revision/generation activation,
retained operation UUIDs after uncertain outcomes, duplicate-click suppression,
cancellation races, replacement, revalidation, permission/flag states, and scoped
realtime refresh. Handoff is displayed separately from recorded publication.

Timezone tests cover explicit IANA input, UTC round trips, New York DST gaps/folds,
non-hour offsets, half-hour DST changes, and display independence from browser zone.
Legacy timestamps without authoring context remain unconfirmed.

Content and Campaign Calendar projections keep stable event keys, one intent event
per channel, separate parent planning, and prior-snapshot labels. Reads do not activate
or mutate work. Existing publication timestamps are preserved; handoff invents none.
Browser component/proxy tests and production builds passed; no deployed browser/IAM
smoke test was performed.

## 8. Security, observability, deployment, and retention

Redaction tests exercise safe worker failures, structured logs, outbox payloads,
API history, and credential-column exclusion. Delivery envelopes allowlist content
fields, bind all routing/revision/approval fields into a canonical fingerprint, and
verify asset digests and immutable bytes. Arbitrary metadata and credential references
are not forwarded. Workspace isolation is tested at repository, API, processor,
calendar, and realtime boundaries.

Committed job gauges and retained event totals are aggregated with bounded query
counts. Correlation IDs persist across replay/recovery. Retained event totals can
decrease if realtime events are pruned; they are not monotonic lifetime counters.

The [worker runbook](scheduling-worker.md) documents caller/runtime identity separation,
private deployment, exact audience, disabled rollout, timeouts, Scheduler cadence,
and transaction-coordinated emergency shutdown. Deployed IAM, database grants,
signature preservation through Cloud Run, dashboards/alerts, and throughput under
production load still require staging evidence.

Scheduling job/transition retention is indefinite, with deletion guards and no TTL
or archival process. Plan storage growth. Any future archival must preserve online
idempotency, receipt readback, and lineage. Channel tombstones remain future work.

`pnpm audit --prod --json` reported **17 advisories: 2 critical, 8 high, 7 moderate**
across Next.js, sharp, PostCSS, and nanoid. This is scanner output, not a claim that
all affected paths are exploitable in LabelOS. Critical reports include
[Windows-hosted Next.js RCE](https://github.com/advisories/GHSA-p293-qw3h-jr36) and
[AVIF image-optimization RCE](https://github.com/advisories/GHSA-2xp9-vwfh-vxw4).
Dependency updates and deployment-specific exploitability triage remain a separate
release gate. `pip check` reports no broken installed requirements; it is not a
Python vulnerability audit.

## 9. Tests and commands

Command results are recorded below. The full backend run started before the
material-edit and eligibility fixes; the final focused run verifies the changed
Scheduling and transaction paths afterward. Raw local
logs and JUnit reports are under `.tmp/scheduling-final-*` (ignored audit artifacts).
Commands requiring PostgreSQL used an isolated test URL, not the application's
configured database. Python package builds used installed build dependencies with
`--no-isolation`; container images were not built or deployed.

| Check                                              | Command                                                                                                                 | Result                                                                  |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Full API backend                                   | `cd apps/api; python -m pytest -q --junitxml=../../.tmp/scheduling-final-backend.xml`                                   | 1540 passed; zero skips                                                 |
| Final Scheduling/transaction/PostgreSQL regression | `python -m pytest tests -q -k 'scheduling or schedule_timezones or content_transactions or marketing_content_postgres'` | 647 passed; zero skips                                                  |
| New workflow/retirement regressions                | `python -m pytest tests/test_scheduling_workflow_postgres.py -q`                                                        | 7 passed                                                                |
| Agent backend                                      | `cd apps/agents; python -m pytest -q`                                                                                   | 21 passed                                                               |
| Frontend                                           | `pnpm test:web`; uncached UI rerun                                                                                      | Web: 503 passed; UI: 3 passed                                           |
| Ruff                                               | `python -m ruff check apps/api apps/agents packages/database`                                                           | Passed                                                                  |
| Pyright                                            | `pnpm typecheck:py`; explicit Scheduling source/service/repository/API/worker/database paths                            | Passed, zero errors/warnings                                            |
| TypeScript                                         | `pnpm typecheck`                                                                                                        | Passed                                                                  |
| ESLint                                             | `pnpm lint`                                                                                                             | Passed                                                                  |
| Prettier                                           | `pnpm format:check`                                                                                                     | Passed                                                                  |
| Production web/UI build                            | `pnpm build`                                                                                                            | Passed                                                                  |
| API/database/agent packages                        | `python -m build --no-isolation --outdir <audit-directory>` in each package                                             | All sdists/wheels passed, including final API rebuild                   |
| Alembic                                            | `heads`; `upgrade head`; `downgrade base`; `upgrade head`                                                               | Single head; final full re-upgrade fails on pre-existing Analytics enum |
| Scheduling Alembic range                           | `upgrade head`; `downgrade 202609061800`; `upgrade head`                                                                | Passed on separate disposable database                                  |
| Dependency security                                | `pnpm audit --prod --json`                                                                                              | Failed: 17 advisories; left outside scope                               |
| Python dependency consistency                      | `python -m pip check`                                                                                                   | Passed                                                                  |
| Patch hygiene                                      | `git diff --check`; scoped Black API formatting/check                                                                   | Passed                                                                  |

### Requested workflow coverage

All runtime acceptance tests use real PostgreSQL. The new
[`test_scheduling_workflow_postgres.py`](../../apps/api/tests/test_scheduling_workflow_postgres.py)
uses the real content/approval/command services and a test-only durable receiver.
API, frontend, race, and migration tests complement that workflow; this is not a
claim of provider or deployed-cloud end-to-end execution.

| Step                                  | Evidence                                                                                                                       |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 1. Multiple stable channel IDs        | New workflow creates four distinct channels and retains their IDs across edits                                                 |
| 2. Destinations, times, IANA zones    | Four destinations; UTC, Kathmandu, New York, Auckland; dedicated DST/timezone suites                                           |
| 3. Current revision approval          | Real submission and independent human approval services                                                                        |
| 4. Activate one channel               | Real Scheduling command with current guards                                                                                    |
| 5. Replay activation                  | Same operation returns same job; one row; concurrent API/repository replay suites                                              |
| 6. Parent time creates no jobs        | Creation with parent time leaves zero jobs before explicit activation                                                          |
| 7. Sibling edit invalidates approval  | New workflow checks revision advance, approval clearing, and sibling retirement                                                |
| 8. Reapprove and replace              | Real new approval, explicit replacement, no implicit jobs                                                                      |
| 9. Concurrent due processors          | New workflow plus separate-connection processor and authenticated HTTP overlap tests                                           |
| 10. One valid lease per job           | Unique claim transitions; held-lock SKIP LOCKED and fencing/expiry tests                                                       |
| 11. Future work unclaimed             | Future job remains pending with fence zero                                                                                     |
| 12. One durable acceptance/key        | Unique transactional inbox and equal receipt replay; conflict/race tests                                                       |
| 13. Crash recovery                    | Lost acknowledgement readback plus injected pre-commit crash/rollback tests                                                    |
| 14. Cancel pending                    | Explicit command in new workflow and API suite                                                                                 |
| 15. Cancelled cannot claim            | Cancelled due channel excluded from concurrent sweeps                                                                          |
| 16. Reschedule/edit/reapprove/replace | New workflow through real service transactions                                                                                 |
| 17. Supersession lineage              | Explicit predecessor and lineage-root assertions; API multi-command coverage                                                   |
| 18. Disconnect blocks                 | Destination disconnected before due sweep; no acceptance, fixed blocked reason                                                 |
| 19. Calendar/realtime/audit/metrics   | New workflow plus projection/outbox/redaction/rollback and frontend cache tests                                                |
| 20. Workspace isolation               | Foreign due work untouched and foreign job lookup denied; API isolation suite                                                  |
| 21. Disabled claims nothing           | Deployment/DB/missing-control/receiver gate tests; authenticated disabled HTTP test                                            |
| 22. Historical rows unactivated       | Migration legacy-data assertions and enabled-sweep legacy regression                                                           |
| 23. No publication fields written     | Parent/channel `published_at`, `external_post_id`, `external_url` stay null; pre-existing values preserved in projection tests |
| 24. No published event                | No `marketing.content.published` in workflow; Scheduling events use their own namespace                                        |

## 10. Scoped fixes

1. Implemented material-edit job retirement in `content_invalidation.py`, using
   existing fenced repository transitions, with author-kind preservation.
2. Aligned activation eligibility with the future-only activation rule.
3. Converted the worker CLI response body to bytes before decoding, resolving
   the expanded Pyright check for Starlette's bytes/memoryview body type.
4. Added seven real PostgreSQL workflow/retirement cases and three overdue
   eligibility API cases. Clarified historical design documentation.

No schema changes, provider implementation, dependency upgrades, deployment
enablement, or unrelated product fixes were made.

## 11. Remaining risks

- No certified production Delivery inbox/adapter or production immutable-asset
  preparation wiring exists. Successful test receivers cannot be deployed.
- Critical/high dependency advisories require separate triage/remediation.
- Full base rollback/re-upgrade is not certified because of the Analytics enum defect.
- Production IAM, restricted database role, Cloud Run authentication boundary,
  operational alerting, and realistic load/capacity are not verified by local tests.
- Indefinite history has storage cost; referenced channel deletion requires a
  future tombstone design. No automatic cleanup may erase replay protection.
- Local verification uses PostgreSQL 17.5/Python 3.14; CI declares PostgreSQL 16/
  Python 3.12. Run CI before merge. Local tests emit existing Python 3.14 migration
  event-loop deprecation warnings.

## 12. Publishing Delivery, retries, and history recommendation

**Go for implementation of the next layer; no-go for production execution.**
Build Delivery-owned durable inbox/receipt persistence and certify the existing
transactional port, idempotency conflict handling, rollback, and uncertain-commit
readback. Prepare approved immutable media before acceptance. Then add provider
execution, provider retry/rate-limit policy, and publication history in Delivery,
with separate acceptance and publication states. Only Delivery should write
provider results and emit publication events after confirmed publication.

Keep both execution controls off until receiver certification, dependency release
gates, staging authentication/permissions, and operational validation are complete.
Scheduling's handoff-unavailability budget must not become provider retries.
