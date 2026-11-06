# YouTube A&R reliability and lifecycle review

Historical provider-layer review. The implemented scouting shortlist and current
local acceptance results are documented in [the checklist follow-up](scouting-checklist-closeout-2026-10-27.txt).

**Historical Prompt 4 review.** The absent-shortlist and pending-local-migration
statements below describe the earlier checkpoint. Prompt 5 adds human reviews and
separately expiring source references, replaces the research permission with
`ar.scouting.view`, and verifies the guarded local migrations. See the
[current validation report](youtube-mvp-validation.md) and
[shortlist contract](youtube-research-api.md#shortlist). Policy approval and a real
authenticated browser workflow remain outstanding.

Review date: 2026-10-27. Status: implementation prepared; migration, public launch,
and policy approval **not performed**. This review is specific to the public
API-key research adapter; it does not certify the separate OAuth publishing flow.

## Official references and policy basis

- [Developer Policies, III.A and III.E.4](https://developers.google.com/youtube/terms/developer-policies):
  non-authorized API data has a maximum 30-day storage window before refresh or
  deletion. Display current data and identify historical data in its time context.
  User-requested deletion must happen as soon as possible and within seven days.
  Consent revocation through the client has a seven-day deletion deadline; Google
  security-settings revocation has a separate 30-day outside limit. Provide terms,
  privacy disclosures, agreement to privacy policy, and a deletion mechanism.
- [Additional derived-metrics and storage policies](https://developers.google.com/youtube/terms/derived-metrics-policy)
  and [compliance guide](https://developers.google.com/youtube/terms/developer-policies-guide):
  additional scores/ratios and extended statistical storage require the applicable
  audited/accepted use case and amendment. No evidence of that acceptance was
  found in this checkout. This implementation does not claim it or enable it.
- [Branding guidelines](https://developers.google.com/youtube/terms/branding-guidelines):
  attribute YouTube features with the appropriate official brand asset. The viewer
  uses the unmodified [official logo asset](https://www.gstatic.com/youtube/img/branding/youtubelogo/svg/youtubelogo.svg),
  linked to YouTube; it does not suggest endorsement.
- [Channel reference](https://developers.google.com/youtube/data/reference/rest/v3/channels):
  subscriber counts are rounded to three significant figures; visibility and
  missing fields must be respected. Missing/hidden values are never converted to zero.
- [Quota calculator](https://developers.google.com/youtube/data/determine_quota_cost)
  and [search.list](https://developers.google.com/youtube/data/reference/rest/v3/search/list):
  the current documentation gives search its own default 100-call daily bucket,
  with one call per page; other endpoints share a 10,000-unit default. The reset
  is midnight Pacific, including daylight-saving changes. This supersedes the old
  assumption that every search consumes 100 units from a shared bucket.

## Storage inventory and implementation decisions

The research routes previously persisted **no provider payload fields**. They
still do not write provider content to the application database. The following
inventory covers every field returned by this adapter and every new stored field.

| Field / location                                                                                                   | Retention decision                                                                                                                                  | Refresh / deletion behavior                                                                                                                                                                                               |
| ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NormalizedArtist.external_id`, `name` (channel ID/title)                                                          | Provider data; never written to SQL. Search/lookup response cache up to 60 seconds, 128 entries/process. Browser view up to 15 minutes.             | Explicit search/refresh; original collection time is preserved on cache hits. Clear action removes local copies; timers expire idle server copies.                                                                        |
| `SourceProvenance.source_url`, provider `country`, subscriber visibility                                           | Same limits as channel metadata, even though the URL is constructed from the channel ID.                                                            | Replaced on live refresh; unavailable lookup invalidates the workspace display cache.                                                                                                                                     |
| `youtube.channel.views`, `.subscribers`, `.videos`, `observed_at`, observation subject ID                          | Current request/browser memory only. No server counter history or Analytics insertion.                                                              | `/channel` obtains metadata and counters in one upstream call. Missing statistics produce an empty observation set. Genuine zero remains zero.                                                                            |
| `next_cursor` / page token                                                                                         | Transient search response only, same 60-second server limit. No pagination crawler or auto-load. Viewer does not retain/use the token.              | Discard on expiry; each explicit API page request spends search quota.                                                                                                                                                    |
| Raw `snippet` / `statistics` HTTP response and credential material                                                 | Request memory only; no raw-response cache or logging.                                                                                              | Discard with request. Credentials are resolved through existing Secret Manager references.                                                                                                                                |
| `collected_at`, `expires_at`, opaque `source_reference`, provider/run/version/workspace IDs in returned provenance | Response metadata, not a new durable snapshot. `expires_at` expresses the 30-day upper bound; implementation uses much shorter memory limits above. | A cached response never receives a new collection timestamp. Future persistence must not copy these response objects into immutable history.                                                                              |
| `attribution`, `license_url`, entity type, identity status, usage restriction, count precision/status              | Static application policy labels except visibility/status, which follow the provider data lifecycle.                                                | Labels disclose source, unverified identity, rounded values and display-only usage.                                                                                                                                       |
| Existing `CollectionRun`, `DatasetVersion`, `DatasetDocumentation`, `GovernanceActivity`, provenance graph         | Existing user-authored governance/operational records; not a payload archive. Existing workspace retention and privacy rules continue to apply.     | Research requests recheck ownership, running state, archived state, and latest eligible production documentation. Failures do not complete runs or change records-written counts.                                         |
| New `youtube_quota_buckets.bucket`, `used`, `reset_at`, `next_at`                                                  | Two content-free operational rows. No channel ID, query, response, credential reference, payload hash or counter value.                             | Usage resets at midnight Pacific. Cooldowns survive process restarts. Rows are overwritten, not appended as history.                                                                                                      |
| User query                                                                                                         | Request/browser memory. Server cache key contains only a SHA-256 digest, expiring with its entry.                                                   | Not logged or stored in database; cleared by the display-data action.                                                                                                                                                     |
| User notes and CRM status                                                                                          | No production A&R candidate/CRM model exists in this checkout. No code writes API values into notes or modifies CRM statuses.                       | Provider expiry must operate on a separate provider-data relation when that missing foundation is implemented. User-authored notes remain subject to deletion/privacy requests, not an unconditional retention exemption. |

No provider-content backup, browser local/session storage, IndexedDB, service-worker
cache, Analytics copy, or audit payload is introduced. HTTP responses use `no-store`.
Server timer eviction works without later traffic. A delete cancels pending cache
population on the current process; other replicas expire their copies within 60
seconds. No automatic refetch runs after deletion. Browser expiry is checked before
rendering and on a one-second tick; suspended tabs purge on resumption. Closing the
view releases its state. There is no persisted payload table requiring a purge job.

The generic Analytics single and bulk insertion paths reject the `youtube`
provider until a separately approved retention/metrics design exists. This does
not retroactively delete any pre-existing production data: none was queried, and
any legacy inventory/purge would require an approved target and a separate plan.

## Reliability controls

- All research credentials/workspaces share two durable deployment-wide budgets:
  80 searches/day and 8,000 channel reads/day. Every actual attempt, including a
  retry or failed upstream request, reserves first in an independent transaction.
  Rotation of a key or creating another workspace does not reset the budget.
- Atomic conditional SQL updates coordinate replicas using the same database.
  Search calls have two-second spacing; channel calls have 250-ms spacing.
  Provider `Retry-After`, quota failures and temporary failures defer the shared
  bucket. Requests rejected by the limiter do not extend their own cooldown.
- Searches have one attempt. Channel reads have at most two attempts, with
  exponential backoff/jitter, five-second attempt timeouts, and the existing
  overall provider deadline. Authentication, deletion, malformed data, quota and
  rate-limit failures are not automatically retried. Long retry hints return to
  the caller instead of keeping a request asleep.
- Identical in-flight search/lookup requests in one process fail fast with a
  retry hint. Results have a small, non-sliding cache. The UI submits searches
  explicitly, disables concurrent submissions, respects cooldowns, never polls
  YouTube, aborts slow requests, and ignores late responses after deletion.
- Empty results, unavailable channels, loading, stale values, timeouts, quota
  exhaustion and errors have distinct user-facing messages. Refresh failures
  leave an existing unexpired display visible with a stale warning; known
  inaccessible channels remove provider content from the view.
- Existing Secret Manager configuration and sanitized provider errors are reused.
  No new log statements contain upstream bodies, requests, credentials, queries,
  titles, counters or external IDs. The web proxy allowlists failure codes and
  preserves `Retry-After` without forwarding diagnostics.

## Database and rollout guard

`202610270100_youtube_quota.py` only adds the two-row operational table. No existing
table or data is altered. Its upgrade requires explicit
`-x youtube_quota_approved=true`; automatic downgrade refuses to reset usage.
The flag is not target approval by itself: an operator must first verify the
approved connection target using the existing isolated database workflow. Do not
run against a recovered database or an unrelated target. No migration was run.

The viewer route is `/research/youtube/<workspace-id>/<collection-run-id>`, for an
existing governed run. It is disabled unless the web server has all of:

```text
YOUTUBE_RESEARCH_UI_ENABLED=true
YOUTUBE_RESEARCH_PRIVACY_POLICY_URL=https://<approved-policy>
YOUTUBE_RESEARCH_TERMS_URL=https://<approved-terms>
```

The viewer requires agreement before requests. These URLs must point to actual,
reviewed LabelOS documents, including storage/use/sharing/contact/deletion details;
the implementation does not invent legal approval. Server governance checks remain
authoritative on every request, including cache hits. Authorizing a collection is
not evidence that YouTube accepted the optional analytics amendment.

## Verification and unresolved items

Use `apps/api/.venv/Scripts/python.exe apps/api/scripts/youtube_reliability_tests.py`.
This runner sets the empty PostgreSQL variable inside Python (PowerShell 5 removes
empty environment variables), overrides the application URL to SQLite and blocks
`asyncpg.connect`. All data is synthetic. It tests expiry, deletion during a pending
fetch, missing/hidden/zero counters, unavailable channels, caching/provenance,
bounded retries, concurrent quota reservation, daily reset/DST, authorization,
collection history and Analytics write rejection. Web tests cover display states,
staleness, expiry, explicit requests and late-response suppression.

An earlier broad test invocation attempted the saved PostgreSQL test target
because of PowerShell's empty-variable behavior. Connection establishment was
refused before schema creation. It was stopped; the Python runner prevents a
repeat. No successful PostgreSQL validation or migration is claimed.

Verification results:

- Guarded regression suite: **414 passed, 52 skipped** (PostgreSQL and unsupported
  provider combinations). After strengthening the Analytics insertion check and
  adding the approval-guard test, the focused reliability suite was rerun:
  **17 passed**. No application behavior changed after the regression run.
- Viewer/proxy tests: **13 passed**; TypeScript typecheck and scoped ESLint/Ruff
  passed. All test provider traffic used mocks.
- A value-free local scan checked 44 log/text files in the root, `.runlogs` and
  `test-results`: no Google API-key patterns, bearer-material patterns or raw
  YouTube counter payload fields matched. This is not a claim about production
  log sinks, crash dumps or logs outside this checkout; those remain an operator
  verification item. Error-path tests also check that fixture secrets do not
  reach response bodies or captured logs.

Release questions requiring review:

1. A production shortlist, candidate notes/status model and research-session UI
   were absent from the available local branches/worktrees and commit history.
   Only a mock scouting agent exists. This change provides a governed research
   viewer, not a replacement CRM. End-to-end shortlist preservation and separate
   persisted notes cannot be certified until that foundation exists.
2. Approve the privacy/terms documents, deletion-contact process, branding and
   A&R use case before enabling the viewer. No optional derived-metrics approval
   was located. Talent scores, engagement ratios and historical counters remain
   disabled; no downloading, audio analysis, scraping or cross-platform metrics
   were added.
3. Confirm actual Google Cloud allocations and external project consumers.
   The shared budgets cover this service's replicas using the same database;
   Google remains authoritative for other software using the same API project.
   Independent deployments must not each claim the full research allocation.
4. Review the separate pre-existing OAuth/social-account and publishing metadata
   lifecycle independently. This public API-key feature neither grants access to
   owner-authorized data nor implements revocation handling for those other flows.
5. Run PostgreSQL concurrency/migration validation only after an isolated target
   is explicitly approved. SQLite atomicity tests do not substitute for that check.
