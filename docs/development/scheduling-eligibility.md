# Shared scheduling eligibility

Implemented against the accepted [Scheduling Engine contract](scheduling-engine-contract.md),
[channel identity foundation](marketing-channel-reconciliation.md), and
[timezone foundation](timezone-safe-scheduling.md). The architecture contract is unchanged.

## Service and result

`services/scheduling_eligibility.py` provides a pure channel evaluator and a batch
adapter for authorized, loaded content parents/channels. It checks workspace and
channel ownership, lifecycle, current/expected revision, approved revision, exact
repository-selected approval authority, channel time and authoring context,
destination identity, provider/artist compatibility, resolver usability, connection
health, publishing capabilities, and server-supplied execution controls.

The immutable result contains `eligible`, `content_revision`, `approval_request_id`,
`scheduled_for` (UTC), `schedule_timezone`, `destination_resolution`,
`automatic_handoff_eligible`, `manual_handoff_required`, `execution_mode`, ordered
`reason_codes`, and matching safe `explanations`. The explicit projection excludes
ORM account metadata, credential references, raw provider errors, and foreign
workspace account details. Marketing and Campaign Calendar channel responses expose
this projection as `scheduling_eligibility`; TypeScript types describe the additive field.

`eligible` and `automatic_handoff_eligible` mean the observed source and execution
readiness checks passed. They do **not** authorize activation, claim work, establish
that a time is due, or prove durable handoff. Only trusted backend callers supply
evidence and controls. Existing API projections use disabled execution and no
Delivery receiver. There is no configuration wiring or user-controlled mode.

The modes are `disabled`, `automatic`, and `manual`. Automatic mode also requires
both execution enabled and a configured durable receiver. Manual mode cannot pass
this initial contract. A manual-only destination reports `manual_handoff_required`
and `manual_delivery_required`, without creating a task. The manual requirement
describes the destination even when other checks, such as approval or health, fail.

The evaluator reuses the existing scheduling blocked codes for approval, lifecycle,
destination, connection, capability, and delivery failures. Additional read-only
diagnostics are `workspace_mismatch`, `channel_mismatch`, `execution_disabled`, and
the timezone foundation's validation codes. These do not extend the job lifecycle
or job blocked-reason contract. Reasons are ordered by ownership/context, revision,
approval, lifecycle, intent/timezone, execution controls, then destination health
and publishing capability. Explanations use fixed application text, never raw
connection errors or approval decision reasons.

## Approval authority

`approvals.load_current_approval_evidence` is the batch equivalent of
`find_conflicting_or_resolved_request`. Both use the same ordering: active requests
first, then newest creation time and ID. The query is scoped to workspace,
`marketing_content_item`, resource ID, and the parent's current revision. It returns
one authoritative request per parent and checks invalidation with a correlated
`EXISTS` query. It does not load or count stages.

An active request takes precedence over approved history, including when the active
request is older. A newer cancelled/rejected request also cannot be bypassed in
favor of older approval. An `invalidated` decision blocks an otherwise `approved`
request. A non-null parent pointer contradicting the authoritative ID blocks
readiness; a null pointer may use the repository evidence. No pointers are repaired
or approvals changed by these reads.

## Existing projections and replaced checks

- Marketing Content lifecycle checks use the shared approval predicate, adding
  invalidation and contradictory-pointer protection to the former status-only
  helper. Parent schedule transitions retain their existing planning semantics.
- Marketing API `approved_revision_is_current` and `can_schedule` use batch-derived
  approval evidence and the shared planning predicate, replacing pointer-only checks.
- Campaign Calendar reuses the same batch results for approval/planning and channel
  eligibility. It retains loaded parent references in internal repository events,
  avoiding the former per-event resource reload for readiness. Event keys, times,
  and display timezone behavior stay unchanged.
- Destination readiness in those projections uses the evaluator's resolver result,
  with the actual workspace and existing artist mapping. Marketing's previous
  resolver call used the account's own workspace and omitted artist context.
- The Social Account resolver now treats `limited` status and recorded health
  errors as unavailable. Pending/reconnect, disconnected, and error retain their
  existing categories. `assisted_action_required` remains a normal manual workflow
  condition. Capability flags alone do not establish usability.
- Approval Queue was inspected in the generic approval service/API and Marketing
  workspace UI. Its review actions and historical request status are approval
  workflow projections, not scheduling eligibility. They remain governed by the
  approval engine; no stage logic or historical request display was replaced.

Planning remains permissive: `can_schedule` still means an approved parent with
current approval and any parent/channel planning timestamp can move to `scheduled`.
It does not require a destination, channel timezone, or enabled execution. An
already scheduled parent has no new planning transition to offer. Assisted and
unhealthy accounts retain their authoring selectability; their delivery readiness
and executable eligibility are separate.

## Query behavior and boundaries

For a nonempty batch with destinations, eligibility adds three SELECTs: ranked
approval evidence, workspace campaign artist IDs, and selected workspace accounts
with a joined artist-profile mapping. Without destinations it uses two; an empty
batch uses none. There are no per-channel queries. Marketing list responses evaluate
the whole page once. Calendar deduplicates parents across its events before evaluation.
Account reads select routing/health fields, refresh those fields from the database,
and omit credential references and provider metadata.

The artist context follows `item.artist_id` or `campaign.primary_artist_id`, matched
through `connection.artist_profile.artist_id`. Workspace-wide accounts remain valid
for artist content under the existing policy. Artist/profile UUIDs are never
compared as if they were the same identity.

The pure evaluator rejects naive instants. The batch adapter normalizes only
unchanged, persisted UTC columns whose timezone was lost on SQLite readback. It
validates the stored local time, IANA zone, and offset through the timezone
foundation without rewriting source intent or generation.

Reads do not commit, create jobs, retrieve credentials, call providers, refresh
health, mutate approval/source records, or dispatch events. Existing calendar
authorization/action lookups still run through the approval service and can issue
per-event queries; eligibility does not add to those and does not bypass them.

## Verification and remaining boundaries

`test_scheduling_eligibility.py` covers valid automatic readiness, every parent
lifecycle, stale revisions/approval/pointers, approval scope and invalidation,
active versus historical authority, missing time/timezone/local context, invalid
zones/offsets/DST intent, missing/foreign destinations, provider/artist mismatch,
limited/unhealthy/reconnect/disconnected accounts, manual-only publication, disabled
execution, missing receiver, safe projection, and planning separation. Database
tests compare one-item and four-item query counts on SQLite and PostgreSQL, check
API planning projection, and reject a planning transition after approval invalidation.

Verification on 2026-09-15:

- Main backend regression: **588 passed**; one calendar API assertion expected the
  old response shape. That assertion now checks the additive eligibility fields,
  and the complete Calendar API suite passed on rerun (**9 passed**).
- Final eligibility suite: **43 passed**, including SQLite and PostgreSQL batch
  authority/query tests. Marketing approval API checks passed (**17 passed**), as
  did the updated planning-versus-execution lifecycle test on both databases
  (**2 passed**). These counts overlap the main regression run.
- Frontend Marketing, Approval Queue, social-account, timezone, calendar, and proxy
  suites: **155 passed** across 11 files.
- Ruff across the API, repository and targeted Pyright, TypeScript, targeted ESLint,
  Prettier, Black formatting for all 11 changed/new Python files, and
  `git diff --check`: passed.

The backend regression command covered scheduling contracts/timezones, Marketing
repositories/service/API/PostgreSQL concurrency, approval repositories/service,
calendar repositories/service/API, social-account service/API/providers/provider
contracts, and database foundation. PostgreSQL used `TEST_POSTGRES_URL` against
local PostgreSQL with the existing isolated, automatically cleaned test schemas.
Migration tests emitted existing Windows asyncio-policy deprecation warnings.

Reproduce from `apps/api` (with `TEST_POSTGRES_URL` set for PostgreSQL coverage):

```powershell
python -m pytest tests/test_scheduling_eligibility.py tests/test_scheduling_contracts.py tests/test_schedule_timezones.py tests/test_marketing_content_repository.py tests/test_marketing_content_service.py tests/test_marketing_content_api.py tests/test_marketing_content_postgres.py tests/test_approval_repository.py tests/test_approval_service.py tests/test_campaign_calendar_repository.py tests/test_campaign_calendar_service.py tests/test_campaign_calendar_api.py tests/test_social_account_service.py tests/test_social_account_connections_api.py tests/test_social_account_providers.py tests/test_social_account_provider_contracts.py tests/test_database_foundation.py -q --tb=short --show-capture=no
python -m ruff check .
```

From `apps/web`:

```powershell
pnpm.cmd exec vitest run src/lib/schedule-timezones.test.ts src/lib/marketing-content.test.ts src/lib/approvals.test.tsx src/lib/social-account-connections.test.ts src/lib/calendar-dates.test.ts src/lib/campaign-calendar.test.ts src/app/marketing/marketing-workspace.test.tsx src/app/campaign-calendar/campaign-calendar-workspace.test.tsx src/app/api/workspaces/approvals-proxy.test.ts src/app/api/workspaces/campaign-calendar-proxy.test.ts src/app/api/workspaces/social-account-connections-proxy.test.ts
pnpm.cmd exec tsc --noEmit
pnpm.cmd exec eslint src/lib/marketing-content.ts src/lib/campaign-calendar.ts
```

From the repository root:

```powershell
pnpm.cmd exec pyright
pnpm.cmd exec pyright apps/api/src/labelos_api/services/scheduling_eligibility.py apps/api/src/labelos_api/repositories/approvals.py apps/api/src/labelos_api/services/social_account_service.py apps/api/src/labelos_api/services/campaign_calendar_service.py apps/api/src/labelos_api/api/v1/marketing_content.py apps/api/src/labelos_api/api/v1/campaign_calendar.py apps/api/src/labelos_api/services/marketing_content_service.py apps/api/src/labelos_api/repositories/campaign_calendar.py
pnpm.cmd exec prettier --check docs/development/scheduling-eligibility.md apps/web/src/lib/marketing-content.ts apps/web/src/lib/campaign-calendar.ts
git diff --check
```

These results remain read observations. Future activation/execution still needs
the approved authorization boundary, parent/channel/approval locking, expected
generation and immutable snapshot checks, lateness policy, active-slot/idempotency
constraints, job history, claim fencing, and a real transactional Delivery receiver.
Health is the latest recorded connection state; the evaluator does not probe
providers or introduce a new health-age/token-refresh policy. Large calendar ranges
still have the existing unbounded event-loading behavior before pagination.
