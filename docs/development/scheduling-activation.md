# Approved channel schedule activation

`services/scheduling_activation.py` implements explicit activation. Its immutable
`ActivateChannelSchedule` command accepts a content ID, channel ID, workspace-scoped
operation ID, expected content revision and expected schedule generation. It has no
time, timezone, destination, approval ID or credential fields. Those values come
from authoritative server records.

`activate_channel_schedule` owns commit and rollback. For composition, use
`SchedulingActivationService(...).activate(command)` inside a caller-owned
PostgreSQL READ COMMITTED transaction and roll back the complete unit on failure.
Both require an authenticated human actor with `marketing.content.schedule` and
workspace/campaign scope, trusted feature controls and an explicit nonnegative
lateness policy. Migration `202609152000` grants the new capability to the global
owner, admin, manager and marketing roles. Custom roles require an explicit grant.

The service locks the parent, campaign, channels, approval requests, existing jobs
and selected destination. It refreshes source state after lock waits and uses the
shared Scheduling Eligibility evaluator, including authoritative approval evidence
and invalidation decisions. The immutable job captures the approved revision,
request ID, exact channel time, explicit timezone, generation, destination and
effective artist (content override, otherwise campaign artist).

This executable-job boundary requires automatic eligibility: authoring and
execution controls enabled, a configured durable receiver and an available
automatic destination. Manual-only destinations are rejected. This is stricter
than the earlier architecture's optional planning-only activation; such planning
jobs are not implemented here. Eligibility does not dispatch or retrieve
credentials, and execution must revalidate independently before handoff.

New activations reject schedules outside the configured lateness window using
database wall-clock time after lock acquisition. Parent planning times never
produce jobs. Historical scheduled rows remain inert until explicitly activated
with current approval and complete timezone context. Activation changes neither
canonical intent nor publication state; changing time or destination remains a
material edit requiring reapproval.

The repository enforces active-job and accepted-intent uniqueness and creates the
pending job plus immutable activation transition. The service inserts a sanitized
`marketing.content.updated` realtime outbox record in the same transaction. There
is no network dispatch. Any failure rolls all three records back.

An authorized retry of the same operation, actor, content/channel and expected
revision/generation returns the original job, including terminal history, without
rechecking changed intent or duplicating audit/outbox records. Reusing an operation
ID with changed command inputs conflicts. PostgreSQL parent locks serialize
concurrent same-channel activation; database uniqueness also guards operation IDs
reused concurrently across different parents.

Tests in `test_scheduling_activation.py` cover success, historical replay,
authorization, approval invalidation, timezone and snapshot validation, generation
guards, parent-only intent, lateness, automatic/manual destinations, artist context,
workspace isolation, rollback, competing activations and material-edit races.
`test_scheduling_activation_migration.py` covers capability migration round trips.
Set `TEST_POSTGRES_URL` to run the real lock and transaction tests; each test uses
and removes its own isolated schema.

Validation: 415 scheduling, persistence, eligibility, contract, content transaction
and database foundation tests passed on SQLite/PostgreSQL as applicable. Another
135 authorization tests passed. After adding cancellation rollback handling,
four focused rollback/material-edit race tests passed (overlapping the main run).
API Ruff, changed-file Black, Markdown Prettier, `git diff --check`, the configured
repository Pyright check and targeted service/repository Pyright checks passed.
An expanded Pyright check of the existing authorization module reports 12 existing
protocol/return-type errors outside the two added capability entries; those were
not changed by this implementation. No application database migration was applied.
