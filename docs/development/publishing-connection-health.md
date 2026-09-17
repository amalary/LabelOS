# Publishing connection and credential health (Stage 6)

Publishing now uses Social Accounts' execution service for connection readiness,
credential retrieval, and refresh. `publishing/youtube.py` no longer queries or
updates connection SQL. `services/social_account_execution.py` delegates OAuth
refresh and secret replacement to the existing connection provider and credential
store. The configured production registry continues to reuse that provider's exact
store instance. No credential backend, OAuth flow, delivery schema, or worker was
added.

## Execution checks

Delivery still validates accepted content, approval, destination and workspace,
then commits an attempt before adapter I/O. Local adapter validation has no I/O.
Before using credentials, Social Accounts loads the connection by workspace and
destination ID and checks provider, direct connection method, retained destination
identity, connected/limited status, revocation/authentication health, and
`content_publish`. A missing or foreign-workspace ID cannot reach the secret store
and cannot update another workspace's health.

The credential reference comes exclusively from that connection. Its material must
be retrievable, use a bearer token, and carry both actual YouTube readonly and
upload grants. Expired, unknown-expiry, or nearly expired credentials (60 seconds)
refresh once through `SocialAccountConnectionProvider.refresh_credentials`.
Refresh-token handling and secret replacement remain in the existing OAuth provider.
Delivery never handles token endpoint requests or stores refreshed tokens.

After refresh, grants, token presence and expiry are checked again. The canonical
connection service applies expiry, scope-derived capabilities and health using a
guarded observation. Empty grants cannot restore default capabilities. YouTube then
verifies the exact access token against the retained channel using `channels.list`.
Connection snapshots are rechecked after credential I/O and again immediately
before the upload. Cached provider metadata cannot authorize a destination.

## Normalized outcomes and health

| Condition                                                                       | Delivery result                        | Connection health                                                                   |
| ------------------------------------------------------------------------------- | -------------------------------------- | ----------------------------------------------------------------------------------- |
| Expired but refreshable, valid refreshed grants                                 | Continue through identity verification | Refresh expiry/grants; clear prior errors; connected or limited according to grants |
| Expired without a refresh token                                                 | `authorization_required`               | `reconnect_required`, `credential_expired`                                          |
| Revoked authorization / OAuth `invalid_grant`                                   | `authorization_required`               | `reconnect_required`, `credential_revoked`                                          |
| Missing reference, missing secret, invalid reference or missing access token    | `authorization_required`               | `reconnect_required`, `credential_missing`                                          |
| Credential backend unavailable, including refresh replacement failure           | `retryable_failure` before upload      | Retain status, `provider_unavailable`                                               |
| Refresh network outage, 5xx or malformed response                               | `retryable_failure`                    | Retain status, `provider_unavailable`                                               |
| Refresh rate limit                                                              | `rate_limited`                         | Retain status, `rate_limited`                                                       |
| Permanent refresh denial                                                        | `authorization_required`               | `reconnect_required`, `refresh_failed`                                              |
| Missing/reduced OAuth scopes, including structured upload permission rejection  | `authorization_required`               | `limited`, `insufficient_scope`; remove only publishing capability                  |
| Disabled/unusable connection (pending, error, reconnect required, disconnected) | Block before credential I/O            | Preserve canonical state                                                            |
| Missing publishing capability or mismatched destination                         | Block before credential I/O            | Preserve canonical state                                                            |
| Live identity mismatch or authoritative provider authentication rejection       | `authorization_required`               | `reconnect_required`, `authorization_failed`                                        |
| Successful authenticated upload                                                 | `published`                            | Clear transient errors; preserve connected/limited status                           |
| Uncertain response after upload begins                                          | `ambiguous`                            | No inferred authentication failure                                                  |

The existing delivery contract maps confirmed authorization failure to terminal
`permanent_failure` with reason `authorization_required`. It does not automatically
reopen an old publication after account repair. Transient failures remain eligible
for an explicit later execution. Unknown upload outcomes still become
`manual_action_required`; health changes never authorize an upload retry.

Canonical capability-specific destination resolution now allows a limited account
with publishing capability, and permits a fresh execution check after transient
connection failures. Scheduling uses this resolution for automatic publishing.
Missing capability and authorization-repair health still block it. Generic and
manual destination resolution retain their existing behavior.

## Health ownership, races and secrets

`social_account_service.load_execution_connection`, `apply_execution_refresh`, and
`record_execution_health` are trusted internal service APIs, not public endpoints
or replacements for management authorization. They restrict changes to expiry,
scope-derived grants, and canonical health/events. They do not rewrite account
identity, ownership, profile associations, credential references or metadata.

Observations compare workspace, ID, provider/method, account identity, status,
capabilities, credential reference, expiry, update timestamp and health error while
holding a short row lock. Reconnect, disconnect, replacement and scope changes
invalidate an old observation. No SQL transaction spans credential-store or provider
I/O. UTC normalization also makes snapshot comparison consistent in SQLite tests.

Health and its event commit together. If health storage fails, the adapter preserves
the authoritative delivery result; a health database outage must not convert a
confirmed upload rejection or success into ambiguous evidence. This health update
is best effort, with no new replay queue. A later canonical health check can repair
the observation. Refresh metadata persistence must succeed before upload proceeds.

SQL and the provider cannot share an atomic transaction: a disconnect after the
final check can still race an already authorized upload. Likewise, existing secret
replacement can finish before a concurrent reconnect invalidates the SQL snapshot;
the stale refresh cannot overwrite the reconnected row or authorize upload.

Credential payloads and snapshots have safe representations. Fixed provider-neutral
codes cross the health boundary; raw exception messages, provider bodies and token
material do not. Publishing requests, results, attempts, transitions and outbox
retain no credential material or credential references. Only the credential backend
stores tokens. Tests inspect all publishing table columns and persisted values,
health messages, events and application logs using secret sentinels. Low-level SQL
driver parameter tracing is not an application logging contract and can expose
opaque connection references; do not enable it for credential diagnostics.

## Verification and Stage 7 readiness

The tests use real SQLite persistence, the existing in-memory credential backend,
the real YouTube OAuth refresh provider and HTTPX MockTransport. They cover every
condition above, missing/foreign destinations, cross-workspace health writes,
stale health updates, reconnect during refresh failure, grant reduction, backend
recovery and health-write failure without loss of delivery evidence.

An additional test runs real Delivery preparation and credential/backend recovery
with a seeded accepted Scheduling source. It adapts SQLite's legacy channel date
read to PostgreSQL UTC semantics; it does not replace authorization checks or claim
to test PostgreSQL row locks. PostgreSQL acceptance/concurrency tests remain part of
the regression suite and require `TEST_POSTGRES_URL`.

Validation on 2026-09-16: the broader publishing, Social Accounts, credential/OAuth
and scheduling regression passed **561 tests**, with **75 PostgreSQL-dependent
tests skipped** because `TEST_POSTGRES_URL` was not configured. After the final
edge cases and access-token-only projection were added, the affected suite passed
**203 tests**. These runs overlap and are not a full API-suite claim. API-wide Ruff,
root Pyright, scoped Black formatting and documentation Prettier checks passed.

```powershell
cd apps/api
python -m pytest tests/test_youtube_publishing.py tests/test_social_account_service.py tests/test_scheduling_eligibility.py -q
```

Stage 7 can build on the configured production registry and normalized outcomes.
This stage does not enable unattended execution or YouTube reconciliation. Production
readiness still needs the PostgreSQL suite, a real approved-media smoke test using
existing OAuth consent/upload scopes, and an operator workflow for terminal account
repair and ambiguous uploads. No live credentials or external upload were used for
this implementation.
