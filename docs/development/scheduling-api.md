# Scheduling authoring and inspection API

All routes live under `/api/v1/workspaces/{workspace_id}`. Reads require
`marketing.content.view`; eligibility and mutations require
`marketing.content.schedule`. Commands require a human user and apply the existing
workspace membership and campaign resource checks. Foreign resources return 404.

| Method | Suffix                                                                              | Purpose                                                                  |
| ------ | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| GET    | `/marketing-content/{content_item_id}/channels/{channel_id}/scheduling/eligibility` | Read current activation eligibility, guards, controls and stable reasons |
| POST   | `/marketing-content/{content_item_id}/channels/{channel_id}/scheduling/activate`    | Activate approved channel intent                                         |
| GET    | `/scheduling/jobs`                                                                  | Inspect workspace jobs with keyset pagination                            |
| GET    | `/scheduling/jobs/{job_id}`                                                         | Inspect an immutable snapshot and its current state                      |
| GET    | `/scheduling/jobs/{job_id}/blocked-reasons`                                         | Read sanitized persisted blocker codes                                   |
| POST   | `/scheduling/jobs/{job_id}/cancel`                                                  | Cancel pending, claimed or blocked work                                  |
| POST   | `/scheduling/jobs/{job_id}/revalidate`                                              | Explicitly return an unchanged, eligible blocked job to pending          |
| POST   | `/scheduling/jobs/{job_id}/replace`                                                 | Activate a successor to blocked, superseded or cancelled work            |

Every POST requires a UUID `Idempotency-Key` header. Activation and replacement
require positive integer `expected_content_revision` and
`expected_schedule_generation` fields. Cancellation and revalidation accept `{}`.
Unknown fields are rejected. There is no endpoint or request field that edits a
job's `scheduled_for`, provides approval evidence, controls execution, or claims
worker authority.

Keys are workspace scoped across all scheduling commands. PostgreSQL transaction
advisory locks serialize retries across targets, and the append-only transition
log records successful commands. Replaying the same key/actor/inputs returns the
original job's **current** representation without another transition or event.
Reusing a successful key with different inputs, targets or commands returns
`409 idempotency_conflict`. Failed transactions do not consume the key. Job,
transition and realtime outbox writes commit together.

The list accepts repeated `status` values, `content_item_id`, `channel_id`,
`connection_id`, `scheduled_from`, `scheduled_through`, `blocked_reason`, and
`provider`. Provider filters the job's workspace-scoped connection. Time bounds
must include an offset and are inclusive. Results sort by creation time then job
ID, descending; pass `next_cursor` back as `cursor` with the same filters. `limit`
defaults to 100 and allows 1–100. Cursor contents never authorize a resource.

Revalidation checks the exact old revision, approval request, generation, time,
timezone, destination and artist context under coordination locks. It also checks
current destination readiness, controls and the database-clock lateness window.
It cannot repair stale approval or move a missed instant. Replacement of blocked
or superseded work requires a material revision and a new completed approval;
the old job is superseded and the successor is linked in one transaction.
Replacement of cancelled work may reuse still-current approval and intent.
Handed-off jobs are immutable; a new publication requires a material revision,
fresh approval, and a new activation. Existing accepted intent cannot be repeated.

Cancellation serializes with durable acceptance using the same source/job locks,
revokes outstanding claims, and remains available after lease expiry. If durable
acceptance wins, cancellation returns `409 invalid_state_transition`.

`SCHEDULING_AUTHORING_ENABLED` defaults to true and gates new activation,
replacement and revalidation. Inspection, cancellation and command replay remain
available when it is false. Effective execution readiness requires both the
deployment execution flag and the workspace database control; receiver readiness
is server derived. The only production receiver remains unavailable, so executable
activation fails closed until a durable adapter is configured. The public API
never invokes a receiver or mounts worker execution routes.

Conflict responses contain `detail.code` and `detail.reason_codes`. Validation
responses contain sanitized `detail` entries with `type`, `loc` and `msg`, without
request input or exception context. Job DTOs omit lease ownership/fences, Delivery
keys/receipts, payloads, provider errors and destination credentials.

Regenerate the checked-in frontend request/response/path types with
`pnpm generate:scheduling-client`; use
`python scripts/generate-scheduling-client.py --check` to detect drift. The source
is the scheduling router's OpenAPI schema. PostgreSQL API tests live in
`apps/api/tests/test_scheduling_api.py` and use `TEST_POSTGRES_URL` with a disposable
schema per test.
