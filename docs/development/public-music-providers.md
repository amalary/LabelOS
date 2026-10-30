# Public music provider adapters — Phase 3, Prompt 11

Official documentation reviewed **2026-10-13**. See the [verification ledger](public-music-provider-verification.md)
for endpoint, licensing, authentication and quota sources, and the
[unsupported-feature report](public-music-unsupported-features.md).

The implementation lives in `apps/api/src/labelos_api/research/adapters` and uses
the [Prompt 10 contracts](research-provider-contracts.md). YouTube is now exposed
through the authenticated [research API](youtube-research-api.md). Other providers
still require explicit composition. There is no collection worker or automatic
provider-data persistence.
Every outbound request uses a fixed official HTTPS API origin and GET. No HTML
scraping, alternate keys, CAPTCHA solving, proxy rotation or authentication bypass
is implemented. Redirects are not followed.

## Capability matrix

These are **implemented capabilities**, conditional on configuration and lawful
access. `ProviderSuite.availability` distinguishes implemented from configured.
No licenses or production credentials were supplied or validated in this task.

| Provider key   | Search              | Artist lookup                          | Catalog                 | Observable counters                               | Access needed                                             |
| -------------- | ------------------- | -------------------------------------- | ----------------------- | ------------------------------------------------- | --------------------------------------------------------- |
| `musicbrainz`  | Artist names        | MBID                                   | Releases and recordings | None                                              | Hosted API use approval; identifying User-Agent           |
| `spotify`      | Blocked             | Blocked                                | Blocked                 | Blocked                                           | Policy prohibits this analysis use case; no enable switch |
| `youtube`      | Channel candidates  | Channel ID                             | Unsupported             | Channel views, rounded subscribers, public videos | Enabled Data API project and API key                      |
| `soundcloud`   | Uploader candidates | User URN                               | Public uploaded tracks  | User followers, public tracks                     | Approved commercial use and OAuth access token            |
| `lastfm`       | Named artists       | Encoded name ID                        | Not implemented         | Artist listeners and cumulative scrobbles         | Commercial/research approval and API key                  |
| `songkick`     | Artists             | Not implemented                        | Unsupported             | None                                              | Paid partnership and API key                              |
| `web_research` | Not implemented     | Wikidata QID with P434 artist evidence | Unsupported             | None                                              | Explicit approval of Wikidata and identifying User-Agent  |

YouTube channels and SoundCloud uploaders are candidates, not verified musical
artists. Their provenance explicitly records that distinction. There is no
automatic cross-provider identity merge.

## Configuration and composition

`ProviderConfiguration` still contains only the workspace/provider binding,
credential reference and timeout. Provision credentials with the existing
`CredentialStore`; do not add plaintext keys to configuration or `.env` files.

| Provider                   | Credential payload fields                                              |
| -------------------------- | ---------------------------------------------------------------------- |
| YouTube, Last.fm, Songkick | `api_key`                                                              |
| SoundCloud                 | `access_token` (sent with the documented `OAuth` authorization scheme) |
| MusicBrainz, Wikidata      | None                                                                   |
| Spotify                    | No credentials can enable the blocked adapter                          |

Token acquisition, rotation and refresh belong to the existing credential/connection
lifecycle. Expired or revoked tokens become `authentication_failed`. Use
`build_credential_store(settings)` in production; it enforces the existing secret
backend policy. `InMemoryCredentialStore` is only for tests/local development.

Example inside an authorized async collection service, after checking workspace,
provider, run, dataset-version and credential-reference ownership:

```python
from labelos_api.research.adapters.common import AccessPolicy
from labelos_api.research.contracts import ProviderConfiguration
from labelos_api.research.registry import ProviderSuite

suite = ProviderSuite(
    {
        "musicbrainz": ProviderConfiguration(
            workspace_id=workspace_id,
            provider_id=musicbrainz_provider_id,
            provider_key="musicbrainz",
            timeout_seconds=20.0,
        ),
        "youtube": ProviderConfiguration(
            workspace_id=workspace_id,
            provider_id=youtube_provider_id,
            provider_key="youtube",
            credential_ref=youtube_credential_ref,
        ),
    },
    credential_store=credential_store,
    policies={
        "musicbrainz": AccessPolicy(
            approval_ref="internal-license-record-id",
            user_agent="LabelOS/1.0 (mailto:real-operator@example.com)",
        ),
    },
)
results = await suite.search_artists("Artist name", contexts, limit=20)
```

Replace the example contact and approval reference with real records. A reference
documents an existing approved use; it does not obtain provider permission.
For Last.fm, SoundCloud and Songkick supply the corresponding policy reference.
For `web_research`, it must approve **Wikidata specifically**. Arbitrary domains,
URLs, search engines, news sites or unofficial platform endpoints are not accepted.
Directly constructed adapters enforce the same access policy before HTTP.

Availability states are `configured`, `not_configured`, `missing_credentials`,
`invalid_configuration`, `approved_use_required`,
`identifying_user_agent_required`, and `policy_prohibits_content_analysis`.
`configured` is not a live credential/health check. Missing secret material or
provider rejection is reported through a typed `ProviderFailure` on invocation.
Search fan-out returns results/failures per configured provider; omitted contexts
are not invoked. It does not combine artist identities or metric values. External
cancellation propagates and individual calls have independent deadlines.

## Data and provenance

`SourceProvenance` has optional additive fields: `source_url`, `attribution`,
`license_url`, immutable `provider_fields`, and `expires_at`. Old contract instances
remain valid. URLs are HTTPS without query strings, fragments or user information.
Provider facts are allowlisted scalar strings, not arbitrary JSON blobs. Raw
responses, private account fields, biographies and credential-bearing URLs are not
retained. This preserves the Prompt 10 boundary around raw-payload ingestion.

MusicBrainz IDs are canonical lowercase MBIDs. Recordings use the normalized
`track` resource while retaining `entity_type=recording`. A release date is populated
only for a full calendar date; a year/month remains in `date_precision`. Multiple
ISRCs are retained as provider fields without choosing one arbitrarily. Supplementary
genres/tags/ratings are not requested or normalized under the core-data license.

SoundCloud uses `soundcloud:users:<number>` and `soundcloud:tracks:<number>` URNs.
Uploader and track artist metadata remain separate. Last.fm uses
`name:<percent-encoded exact name>` consistently, including artists without MBIDs;
name identities can change with provider corrections. MBIDs remain evidence, not
cross-provider joins. Songkick IDs are decimal strings; Wikidata IDs are QIDs and
include the source revision and nondeprecated P434 MusicBrainz artist assertions.

Supported metric keys are:

| Provider   | Metric keys                                                                      | Meaning                                                                            |
| ---------- | -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| YouTube    | `youtube.channel.views`, `youtube.channel.subscribers`, `youtube.channel.videos` | Returned channel counters; subscribers rounded to three significant figures        |
| SoundCloud | `soundcloud.user.followers`, `soundcloud.user.tracks`                            | Returned follower and public track counts                                          |
| Last.fm    | `lastfm.artist.listeners`, `lastfm.artist.playcount`                             | Returned cumulative listeners/scrobbles; not platform streams or monthly listeners |

Observations are current snapshots with collection time and integer `count` units.
Missing/hidden counters stay absent; actual zero is retained. Unsupported metrics
fail explicitly. Requests whose `[start_at, end_at)` excludes collection time fail
as unavailable; there is no historical backfill. All requested metrics must fit
one page; observation cursors and partial metric pages are rejected.

YouTube provenance expires in 30 days. Consumers must enforce its retention and
display policies, and must not feed these counters to A&R scores, derived metrics
or cross-owner aggregation. SoundCloud facts carry `retention=session_only`;
consumers must discard them at session end. This suite performs no persistence and
does not grant downstream storage or redistribution rights.

## Pagination, failures and pacing

One call retrieves one page. MusicBrainz offsets advance by actual records returned.
Last.fm/Songkick use page numbers; YouTube uses documented page tokens. SoundCloud
returns random opaque handles backed by at most 128 private continuation entries,
bound to collection context, path, query, resource and limit. Reuse the adapter
instance for continuation; restart/eviction requires starting again. It validates
the next URL's origin/path and extracts only the cursor; it never follows that URL.

`RequestGate` shares process-local pacing by provider. MusicBrainz starts at most
one request per second; Wikidata uses conservative one-second pacing. Other quotas
are not represented as invented universal limits. A premature call fails fast with
`rate_limited`; nothing sleeps or automatically retries. HTTP 429/503 and vendor
rate-limit responses establish a cooldown, honoring valid `Retry-After` hints.
The collection scheduler must apply provider/project quota budgets and a shared
egress limiter across processes. Never create extra keys/IPs to evade restrictions.

Transport and JSON errors pass through the existing sanitized `ProviderClient`
boundary. Vendor quota/authentication errors are translated before generic HTTP
fallbacks. Injected transports are caller-owned and must be closed by their owner.
The default transport has no automatic retries, redirects, environment proxies or
cookies. It avoids HTTPX's INFO URL logging; injected transports and production
tracing must also keep request URLs, headers and response payloads out of logs.

## Tests

From `apps/api`:

```sh
python -m pytest tests/test_research_providers.py tests/test_public_music_adapters.py -q
python -m ruff check src/labelos_api/research tests/test_public_music_adapters.py tests/research_provider_contracts.py
```

The suite extends `ResearchProviderContractTests` with provider-specific requests.
Synthetic JSON fixtures and `httpx.MockTransport` cover supported operations,
malformation, authentication, throttling, quotas, identity/provenance, missing
metrics, paging, policy gates and independent provider failures. Skips in the
shared failure suite denote undeclared operations; the success suite explicitly
asserts those operations return `unsupported_operation`. No external API or
database is needed for these tests.
