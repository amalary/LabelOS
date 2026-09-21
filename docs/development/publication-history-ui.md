# Stage 11: publication history and delivery tracking

Open saved content in Marketing to inspect **Publication history**, beneath the
channel scheduling controls. It includes every destination and accepted revision
for that content item, including channels removed from the current draft.
**View delivery details** shows the approved caption, hashtags and prepared asset
references; destination; scheduling job, generation, time and timezone; delivery
timestamps; safe failure reason; provider reference; and chronological attempts.
The content inspector supplies the associated campaign and artist context.

Delivery status and product resolution remain distinct. A manual completion shows
the human completion time and reference without inventing provider success or an
additional execution attempt. Unknown outcomes require reconciliation before a
new delivery. Retry scheduling, reconnection, exhausted retries and manual work
each have explicit guidance. Delivery details now offer the existing recovery
commands when their canonical eligibility flags and caller permissions allow them.

## Phase 2 recovery actions

- **Retry** posts to `recover` with delivery/action versions and a UUID idempotency
  key. It does not reset exhausted budgets or retry permanent/unknown outcomes.
  Account authorization failures require a restored connection before Retry appears.
- **Reconnect Account** uses the existing Social Account Connection OAuth start
  and callback for configured direct YouTube connections, in a separate window.
  The original handoff stays open. Accounts displays callback success/failure;
  returning to the handoff refreshes connection and publication state. Other
  connection methods link to Accounts; no new provider support is introduced.
  Reconnection never submits a publishing command.
- **Reserve manual delivery** calls `manual/start` before a human publishes.
  The reservation suppresses automatic delivery and cannot be released to it.
  The approved caption, hashtags and authenticated prepared-asset downloads are
  available in the handoff. **Mark publication completed** requires an explicit
  delivery attestation and accepts optional resource ID/public HTTPS URL using
  the existing backend contract. It preserves all automatic attempts.
- `manual_action_required` represents an uncertain provider outcome in this
  backend. It remains reconciliation-only; no blind retry or human completion
  bypass is offered. Published, cancelled and manually completed work is read-only.

The safe handoff adds `can_manage_recovery` (human plus workspace/campaign
`marketing.content.schedule` authorization), `can_manage_account` (human plus
`marketing.account.manage`), and matching destination connection method/status.
These permission projections are separate from lifecycle eligibility flags.
Missing projections fail closed. Every command still rechecks backend authorization,
versions, approval, destination and recovery policy; a stale command is rejected.

Buttons lock synchronously against double submissions and remain disabled during
canonical refresh. Uncertain command outcomes retain their idempotency key for
an identical retry. Conflicts and failures refresh canonical state and show fixed,
non-provider error messages. Mutation receipts do not replace attempt history.

## API and refresh behavior

The content-scoped publication list and detail APIs retain their
workspace/campaign authorization. The list now returns `PublicationSummary`:
identity, destination display identity, accepted channel/placement/revision and
schedule, lifecycle/resolution, attempt count, latest failure, public provider
reference and recovery eligibility. Content title, campaign and artist labels
continue to come from the content inspector. The list has no media or thumbnails.
Origin IDs, prepared captions, hashtags, asset references, individual attempts,
observations, actions and account-management controls are fetched separately from
the existing detail endpoint when a row is expanded. Attempt completion remains the original execution
observation time; subsequent reconciliation is shown separately on that attempt.
`latest_failure_reason` and `last_failed_at` describe the most recent recorded
failure, even if a later attempt succeeded.

Authenticated Next.js read and recovery command proxies serve these projections with `no-store` and
replace failed upstream responses with generic errors. Browser failures use
fixed messages, never raw HTTP bodies or arbitrary exception text. Failure codes
map to fixed user-facing text. Provider links require public HTTPS URLs without
userinfo, query, fragment or nonstandard port. Credentials, tokens, authorization
headers, provider response bodies, arbitrary metadata and embedded media bytes
are absent from the history projection.

### Phase 2 performance closeout

The former list called `PublicationRecoveryService.get()` and `handoff()` for
each ID. Each call loaded the full binary canonical envelope, attempts,
observations, transitions and actions, repeated content/channel authorization
loads and capability queries, and looked up the destination separately. Polling
every 15 seconds repeated these loads even with all details collapsed.

`services/publication_history.py` now checks workspace and campaign view access
once per page and schedule permission once for recovery visibility. It reads
only the content campaign ID for authorization. The repository uses one bounded
scalar query: workspace/content filters and the existing UUID cursor order select
at most `limit + 1` publications (API maximum 100); one-to-one joins provide small
snapshot, immutable scheduling-job and scoped destination fields. Indexed scalar
count/first-attempt and latest-action/latest-failure selectors provide summaries
without materializing any journal collections. Recovery resolution shares the
existing policy logic; commands still perform their complete authorization and
state checks. No rich Publication or content ORM graph is hydrated by listing.

Migration `202609170500` adds `publication_list_metadata`, keyed by Publication
with a composite workspace foreign key. It stores only the accepted channel and
placement, which must survive later draft edits. Creation writes it atomically
with acceptance. A database-side backfill extracts these fields once from existing
envelopes, without altering the immutable journal. The existing content index is
extended to `(workspace_id, marketing_content_item_id, id)` to serve precisely the
filter, cursor and ordering used here. Existing attempt-number, action-version
and transition-version indexes serve the summary lookups; no others are added.

Deploy the migration and new acceptance writers together with old acceptance
workers quiesced; resume writes only on the new version. The one-time envelope
backfill and index replacement require a migration window appropriate to database
size. There is deliberately no expensive envelope fallback in list reads.

The repeatable fixture in `test_publication_history_projection.py` includes 25
publications in the requested content scope, another content item in the same
workspace and another workspace/content item,
three named destinations, 36 attempts, and two 128 KiB media assets in each of 24
accepted envelopes. It also puts 256 KiB of unrelated metadata on the current
content item and changes a draft placement. SQLAlchemy cursor instrumentation
replays the old endpoint and compares it with the new API in fresh sessions:

| Page size | Former SELECTs | New SELECTs |
| --------- | -------------: | ----------: |
| 1         |         50–51* |          24 |
| 5         |       198–199* |          24 |
| 25        |            938 |          24 |

*The pending row's random UUID position determines whether an observations query
is needed. Counts include real RBAC reads, but not test setup or transaction
control. Both SQLite and PostgreSQL reproduce the constant new count. One of the
24 queries is the entire publication projection; the rest are authorization and
the campaign-ID lookup. The former 25-row read selected 25 full envelopes (about
8 MiB of embedded base64 media across 24 rows); the new list selects none. Tests
also reject asset/content-metadata columns and channel hydration in captured SQL.
SQLite EXPLAIN verifies use of the content cursor index; PostgreSQL EXPLAIN ANALYZE
verifies the bounded result. Backfill tests rebuild all 27 metadata snapshots from
the representative dataset and compare them with the snapshots captured on acceptance.

Remaining costs are the existing constant authorization reads, one summary lookup
per returned publication inside the bounded SQL query, and polling each page the
user has loaded. An expanded detail still uses the rich endpoint and asset
downloads still read the prepared snapshot. These behaviors are intentionally
outside this listing-only fix. Production latency and migration duration should
be observed at deployment; the regression measurements are query/load counts,
not a production throughput benchmark.

Closeout verification: Publication History API/projection, recovery, retry,
publishing persistence/migration, PostgreSQL recovery and invalidation suites
pass on the applicable SQLite/PostgreSQL backends. This includes query-count and
no-media assertions, current and revoked permissions, campaign denial, public
destination identity, manual/provider outcome parity, stable cursor pagination,
same-workspace content isolation and media-bearing migration backfill. The 154
targeted frontend tests (history, client, proxy and Marketing workspace) and the
frontend typecheck pass. The history tests use the exact summary field set and
verify that repeated 15-second polls never fetch rich details while collapsed;
expansion fetches the detail endpoint, and collapsing stops those detail reads.
Changed Python files pass Ruff. The MEDIUM listing performance finding is CLOSED in code, with the
migration/deployment sequence above required before rollout.

Closeout rerun: 122 backend tests passed without PostgreSQL (five PostgreSQL-only
tests skipped). With PostgreSQL enabled, the selected run passed 154 tests and had
one connection timeout during recovery-test setup after a long execution pause;
that test passed on immediate isolated rerun (155 selected tests verified in total).
The timeout occurred before exercising publication behavior. No application change
was made for it. The disposable PostgreSQL server was stopped after verification.

The panel supports cursor pagination, refreshes all loaded pages on delivery
events and social-account changes, refreshes on window focus, and polls every 15 seconds while visible. Scope changes abort in-flight
reads and remount state; failed reads clear previously loaded evidence. Loading,
empty, denied, unavailable and retry states use existing UI components.

## Verification

- API history tests cover pending delivery, view-only access, content/workspace
  scope, pagination, failed-then-successful attempts, manual completion and the
  explicit safe attempt field set.
- Frontend tests cover delivery states, approved content, ordered attempts and
  reconciliation, recovery guidance, resource links, safe errors, pagination,
  realtime notifications and stale responses after a scope change. Recovery tests
  cover visibility, authorization, successful/failed retry, duplicate submissions,
  uncertain-outcome idempotency, stale conflicts, OAuth reconnection, manual
  reservation/completion, input validation, asset download proxies and terminal
  publication states.
- Existing recovery, scheduling, marketing workspace and realtime suites remain
  regression checks for integration with the established workflows.
