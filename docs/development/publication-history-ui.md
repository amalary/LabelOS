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

The existing content-scoped publication list and detail APIs retain their
workspace/campaign authorization. Their explicit public projection now includes
origin IDs, lifecycle timestamps, attempt count and individual attempts with
normalized observations. Attempt completion remains the original execution
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
