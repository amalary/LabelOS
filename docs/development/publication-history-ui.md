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
each have explicit guidance. This inspection surface performs no delivery
mutations; reconnection links to the existing Marketing Accounts tab.

## API and refresh behavior

The existing content-scoped publication list and detail APIs retain their
workspace/campaign authorization. Their explicit public projection now includes
origin IDs, lifecycle timestamps, attempt count and individual attempts with
normalized observations. Attempt completion remains the original execution
observation time; subsequent reconciliation is shown separately on that attempt.
`latest_failure_reason` and `last_failed_at` describe the most recent recorded
failure, even if a later attempt succeeded.

Authenticated Next.js GET proxies serve these projections with `no-store` and
replace failed upstream responses with generic errors. Browser failures use
fixed messages, never raw HTTP bodies or arbitrary exception text. Failure codes
map to fixed user-facing text. Provider links require public HTTPS URLs without
userinfo, query, fragment or nonstandard port. Credentials, tokens, authorization
headers, provider response bodies, arbitrary metadata and embedded media bytes
are absent from the history projection.

The panel supports cursor pagination, refreshes all loaded pages on delivery
events, and polls every 15 seconds while visible. Scope changes abort in-flight
reads and remount state; failed reads clear previously loaded evidence. Loading,
empty, denied, unavailable and retry states use existing UI components.

## Verification

- API history tests cover pending delivery, view-only access, content/workspace
  scope, pagination, failed-then-successful attempts, manual completion and the
  explicit safe attempt field set.
- Frontend tests cover delivery states, approved content, ordered attempts and
  reconciliation, recovery guidance, resource links, safe errors, pagination,
  realtime notifications and stale responses after a scope change.
- Existing recovery, scheduling, marketing workspace and realtime suites remain
  regression checks for integration with the established workflows.
