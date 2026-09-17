# Stage 10: terminal failure and manual publishing

This stage adds a product resolution workflow to accepted Publications, without
an infrastructure dead-letter queue or changes to Scheduling ownership.
`PublicationRecoveryService` provides authorized inspection, manual reservation,
manual completion and remediation commands. Migration `202609170300` introduces
`PublicationAction`, a durable, append-only human action journal.

## State behavior

The API returns both `delivery_status` (automatic delivery history) and
`resolution` (current product outcome). Consumers must use `resolution` when
presenting completion or deciding which human action to offer.

| Situation                                                                        | Resolution                    | Next step                                                                                 |
| -------------------------------------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------- |
| Definitive transient failure with budget remaining                               | `retry_scheduled`             | Worker retry, or manual reservation                                                       |
| Five attempts or original 24-hour budget exhausted                               | `retry_exhausted`             | Manual reservation; no budget reset                                                       |
| Unsupported operation, unavailable publishing adapter or API capability          | `terminal_failure`            | Manual reservation; corrected automation requires new approved work                       |
| Permanent rejection or unsupported content/media                                 | `terminal_failure`            | Review rejection; manually deliver the same approved content, or create new approved work |
| Missing credentials, reconnect flag, disconnected account or insufficient grants | `reconnect_required`          | Restore the same account and request recovery, or reserve for manual publishing           |
| Definitive local/internal failure                                                | `human_intervention_required` | Remediate and request recovery, or reserve for manual publishing                          |
| Unknown outcome or interrupted executor                                          | `reconciliation_required`     | Authoritative reconciliation; no blind retry or new manual publication                    |
| Human reserved failed work                                                       | `manual_publishing`           | Human publishes and confirms completion                                                   |
| Human confirmed delivery                                                         | `manually_completed`          | Terminal product outcome; read history only                                               |
| Remediation authorized within original budget                                    | `retry_authorized`            | Worker revalidates and starts one new attempt                                             |

Unsupported adapters/capabilities now produce a committed local attempt and
definitive unsupported failure without provider I/O, replacing the old behavior
that left work pending. Account health blockers discovered after acceptance also
produce durable classified observations. Approval, revision, identity,
cancellation and snapshot validation still fail closed.

Permanent automatic failure remains terminal in the delivery aggregate. Manual
completion does not fabricate provider evidence or change that aggregate to
`published`: it appends a human completion with `completion_source: human` and
optional external ID/URL. Earlier attempts and transitions remain unchanged.
Verified automated success uses `completion_source: provider`. Legacy failures
without automatic eligibility appear as human action work.

## APIs and handoff

Paths below are relative to `/api/v1/workspaces/{workspace_id}/publications`.

| Method and path                                     | Behavior                                                            |
| --------------------------------------------------- | ------------------------------------------------------------------- |
| `GET ?content_item_id={id}&limit=100&after_id={id}` | Bounded content-scoped list with `next_after_id`                    |
| `GET /{publication_id}`                             | Handoff, resolution, delivery history and human history             |
| `GET /{publication_id}/assets/{sha256}`             | Exact accepted asset, digest verified, attachment, private/no-store |
| `POST /{publication_id}/manual/start`               | Reserve failed work; suppress worker claims and starts              |
| `POST /{publication_id}/manual/complete`            | Confirm delivery; optional `external_post_id` and `provider_url`    |
| `POST /{publication_id}/recover`                    | Authorize one retry after remediation checks                        |

POSTs require a nonzero UUID `Idempotency-Key` and JSON containing
`expected_version` (delivery transition version) and `expected_action_version`
(zero before the first human action). Completion additionally requires
`delivery_confirmed: true`. IDs/URLs may be omitted when unknown. URLs must be
HTTPS without userinfo, query strings or fragments. Exact replay by the same
authorized human creates no additional action/outbox record. Changed inputs,
stale versions and illegal operations return 409; inaccessible scoped IDs return
404; authorization denials return 403.

Handoffs expose provider, destination ID, matching account ID/name, caption,
hashtags, digest/media/size asset references, channel, placement, approved revision,
scheduled instant, timezone and safe failure reasons. Account details are withheld
if the current identity differs from the accepted identity. No connection objects,
credentials, credential references, raw provider responses or arbitrary metadata
are serialized. Embedded asset bytes are available only through the separately
authorized download route.

## Authorization, audit and legal transitions

- Reads/downloads require `marketing.content.view`; mutations require
  `marketing.content.schedule`, at both workspace and campaign scope.
  Only authenticated human users can mutate. Agents may inspect authorized work.
  Omitting the actor cannot bypass service authorization.
- Manual start rechecks current approval, unchanged content/envelope, source job
  and destination identity under existing source-to-publication locks. Account
  automation blockers are allowed. Completion records the reserved immutable
  intent, including when content changes after a human has begun publishing.
- Recovery permits only definite `blocked_reconnection` and `manual_action`
  failures. Full automatic preparation rechecks approval, content, destination
  identity, health and publishing grants. A health update alone never retries.
- Recovery retains the first-attempt-plus-24-hour deadline and five-attempt limit.
  A grant is bound to one failed transition version; a new start consumes it by
  advancing that version. Worker selection, execution and SQL attempt guards all
  enforce eligibility. Permanent failures and exhaustion cannot be reset.
- Manual reservation blocks workers, explicit starts and cancellation. It cannot
  be released to automation because the human may already be publishing.
  Unknown outcomes, interrupted executors and active ownership require existing
  reconciliation/lease resolution before entering this workflow.
- Commands lock the publication and check delivery and action versions. SQL
  guards enforce legal action sequences and immutable history. Composite foreign
  keys enforce publication/workspace ownership. Concurrent completion produces
  one action. Actor ID, operation ID, reason, timestamp, referenced delivery
  version and optional external evidence are retained. Action and safe realtime
  outbox event commit atomically, preserving every failed automatic attempt.

## Validation and Stage 11

`test_publication_recovery.py` covers API authorization, agents, existing foreign
workspaces, completion with/without IDs, replay, immutable audit, unsafe URLs,
asset downloads, retry exhaustion/expiry and prevention of direct-SQL attempts
after reservation. `test_publication_recovery_postgres.py` covers real source
preparation, restored connection/grants, changed identity/content rejection,
worker grant consumption and competing human completions. Existing publishing,
YouTube, retry, lease and persistence/migration suites provide regression coverage.

Verified on 2026-09-17: all 557 tests in the affected publishing/provider/retry/
worker/recovery/persistence suites passed using SQLite and an isolated PostgreSQL
17 cluster. API Ruff, changed-file Black, configured Pyright (including the new
service and API), documentation Prettier and `git diff --check` passed. External
provider calls were mocked; this is not a claim of a completed whole-API test run.

Apply migration `202609170300` before starting updated API or worker processes.
Downgrade refuses to discard existing human action history; it cannot safely
return manually delivered work to workers that do not recognize that history.
Stage 11 can consume these APIs and resolution fields for an operator interface
and agent inspection. This stage provides the backend workflow; it does not add
a frontend or expand provider support. Uncertain YouTube uploads still require
authoritative investigation; a human assertion cannot authorize a duplicate.
Legacy assisted-content completion fields are not imported as Publication evidence.
