# YouTube publishing adapter (Stage 5)

`publishing/youtube.py` implements the Stage 4 provider protocol using the official
YouTube Data API v3. `publishing/registry.py` supplies explicit production adapter
composition. No second OAuth flow, secret store, schema, public endpoint, worker,
or scheduling policy is introduced.

## Supported content and mapping

- Canonical provider/channel `youtube`, placement `video` or `shorts`.
- Exactly one approved `video/*` asset, nonempty and SHA-256 matched. The existing
  Scheduling envelope limit remains 16 MiB per asset; this is a LabelOS limit.
- The caption's first line is the title, preserved without truncation; it must be
  nonblank and at most 100 characters. The description contains the full caption
  followed by two newlines and space-separated approved hashtags, when present.
- Descriptions are limited to 5,000 UTF-8 bytes; unsupported angle brackets and
  control characters are rejected locally. No generated title or added hashtag.
- Automatic publication requests public visibility. The current accepted envelope
  has no independent title, privacy, category, audience, synthetic-media disclosure,
  thumbnail, playlist, or YouTube scheduling settings. Those are not inferred from
  mutable metadata. Content needing those controls is outside this adapter's scope.

Both placements use `videos.insert`; there is no separate Shorts creation endpoint
or Shorts flag. YouTube classifies eligible uploads according to its own rules;
LabelOS does not inspect duration/aspect ratio or promise Shorts placement. See
[YouTube's Shorts guidance](https://support.google.com/youtube/answer/15424877).
Community posts, images, text-only posts, carousels, live streams, stories,
playlist changes, thumbnails, updates and deletions are not supported here.

## Execution and credentials

1. Delivery revalidates the accepted publication, locally validates the adapter
   request, and commits the attempt before calling the adapter.
2. The adapter reads the SocialAccountConnection by **workspace and destination
   ID**, requires `direct_api`, a connected/limited state, `content_publish`, and
   a credential reference. It checks the retained SHA-256 identity fingerprint.
3. It reads the credential from the existing OAuth provider's exact store instance.
   Both `youtube.readonly` and `youtube.upload` must be in actual granted scopes.
   SQL capabilities or requested scopes alone cannot grant permission.
4. Expired, unknown-expiry, or nearly expired credentials refresh through
   `YouTubeDirectSocialAccountConnectionProvider.refresh_credentials`. That existing
   implementation handles the Google token endpoint, refresh-token preservation,
   and credential replacement. A short conditional SQL update persists expiry and
   scope-derived capabilities only if the connection version/reference still match.
   No management API authorization is bypassed or relaxed.
5. `channels.list(part=id,mine=true)` verifies the exact upload access token against
   the retained channel. Cached connection metadata is insufficient. The connection
   is read again to detect reconnect/disconnect/replacement during credential I/O.
6. One `videos.insert` multipart/related request uploads approved bytes and metadata
   and creates the video. Redirects and automatic write retries are disabled.
7. A successful response must contain a `youtube#video`, a valid 11-character video
   ID, and the expected channel ID. The adapter returns the normalized final ID.
8. Delivery persists evidence, Publication state, attempt observation, transition,
   and realtime outbox atomically through the existing version-guarded repository.

No database transaction or lock spans secret-store or network I/O. A disconnect
after the final check can still race an already authorized external request;
external publication and SQL cannot form one atomic transaction.

Required scope URLs are:

```text
https://www.googleapis.com/auth/youtube.readonly
https://www.googleapis.com/auth/youtube.upload
```

The existing OAuth connection API accepts these scopes. Its default and the
current generic Connect YouTube UI remain read-only; an existing read-only
connection needs explicit upload-scope consent through that same OAuth flow.
Analytics scopes are unnecessary for publishing. Offline consent and production
secret-backend restrictions remain unchanged.

## Result meaning and error handling

`published` means **the video resource was authoritatively created**. Its final ID
is durable and is not an upload-session or processing-job identifier. It does not
prove transcoding completion, playback availability, Shorts classification, or
public reach. YouTube may restrict an upload despite requested public visibility;
in particular, unverified projects can be restricted to private uploads. These
restrictions must be resolved before public rollout. See the official
[videos.insert reference](https://developers.google.com/youtube/v3/docs/videos/insert).

Only documented structured Google rejection reasons from the single insert request
establish noncreation: invalid content becomes permanent failure; permission errors
require authorization repair; quota/rate/upload limits become rate-limited with an
optional bounded integer Retry-After hint. There is no inline retry loop.

Before upload, missing/revoked credentials, missing scopes, wrong channel, or changed
connection require authorization repair. Store/network unavailability is retryable
because media has not been sent. After upload begins, network exceptions, 5xx,
redirects, unknown errors, malformed responses, and missing/invalid IDs are
ambiguous. Delivery persists `manual_action_required` and prevents another execute.
Only an explicit later execute can retry confirmed noncreation.

Reconciliation is deliberately unsupported: YouTube does not expose lookup by the
LabelOS idempotency key. Caption/time searches cannot establish absence. There is
no exactly-once claim, durable resumable receipt, automatic recovery, or background
polling. A crash after YouTube creation but before result persistence needs manual
inspection; the Stage 3 interrupted-attempt recovery rules still apply.

## Stored identifiers and safe data

- `Publication.provider`: canonical `youtube` (already retained at acceptance).
- `external_post_id` in Publication, normalized evidence/transition, and the attempt
  observation: the authoritative YouTube video ID.
- Existing destination ID/fingerprint and normalized lifecycle/failure reason.
- Connection refresh updates only its existing credential reference's contents,
  SQL expiry, and scope-derived capabilities.

No raw provider metadata, response bodies, error messages, token values, authorization
headers, credential copies, or upload URLs are logged or added to publishing SQL or
outbox. The adapter adds no logging. There is no new credential representation in
the public provider contract and no arbitrary metadata extension.

## Composition and Stage 6

The trusted execution host must reuse its configured Social Accounts registry:

```python
from labelos_api.publishing.registry import publishing_provider_registry

registry = publishing_provider_registry(
    sessions=sessions,
    social_account_registry=social_account_registry,
)
await orchestrator.execute(
    sessions,
    workspace_id=workspace_id,
    publication_id=publication_id,
    registry=registry,
)
```

Only a configured direct YouTube OAuth adapter with a credential store registers.
Assisted connections and other providers do not get fallback publishing support.
Omitting a registry continues to fail closed. Stage 6 can integrate this factory
with its trusted execution host; this stage does not enable an unattended worker.

Production rollout still requires configured OAuth/upload consent, Google project
verification where applicable, a real media smoke test, and an operator procedure
for ambiguous outcomes. Additional publication controls or resumable recovery need
explicit content/receipt contracts rather than heuristics inside the adapter.

## Verification

`tests/test_youtube_publishing.py` uses HTTPX MockTransport, the existing in-memory
credential store, the real OAuth refresh implementation, and real SQLite publishing
persistence. Only Scheduling preparation is substituted; its authorization and
locking are covered by the existing delivery suite. Tests have no external network
or real YouTube dependency.

Validation on 2026-09-16: all 74 new adapter cases passed. The final adapter/provider/
domain run passed 256 cases. A broader publishing persistence, delivery, Social
Accounts, credential-store and OAuth regression passed 407 cases with 43
PostgreSQL-dependent cases skipped (no `TEST_POSTGRES_URL` configured). That broader
run preceded the final 16 added edge cases; no full API or PostgreSQL regression is
claimed. API-wide Ruff, root Pyright, scoped Black formatting and documentation
Prettier checks passed.

```powershell
cd apps/api
python -m pytest tests/test_youtube_publishing.py tests/test_publishing_providers.py tests/test_publishing_contracts.py -q
```

Coverage includes multipart bytes/metadata, publication/outbox persistence, scoped
connection lookup, live account binding, scope checks, refresh/revocation and reduced
grants, connection races, provider errors, ambiguous results, and duplicate prevention.

Local OAuth client ID and secret were both absent; the configured store backend was
memory. No real external smoke test was possible or attempted. A future manual
smoke test must use an existing connected account with upload consent and an approved
small video through the same acceptance/execution path; it must not introduce token
files or a separate OAuth script. Check the saved ID in YouTube Studio, including
processing/visibility, before authorizing unattended delivery.

API protocol verified against Google's
[YouTube discovery document](https://www.googleapis.com/discovery/v1/apis/youtube/v3/rest),
whose `videos.insert.mediaUpload.protocols.simple.multipart` is `true`, and the
[video resource limits](https://developers.google.com/youtube/v3/docs/videos).
