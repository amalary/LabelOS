# Official API verification ledger

Reviewed **2026-10-13** before implementation. This records public documentation,
not a claim that LabelOS holds a license or has working credentials. Only official
provider sources informed endpoint implementation. Fixtures are synthetic.

## MusicBrainz

The hosted API supports GET artist search/lookup and artist-filtered release and
recording browse. JSON uses `fmt=json`; browse supports limit/offset up to 100.
Public reads do not require login. Commercial hosted API use needs an arrangement;
the adapter requires its reference and a meaningful User-Agent.
[API documentation](https://musicbrainz.org/doc/MusicBrainz_API).

The standard limit is one request per second per source IP; throttling can return 503. The adapter advertises and locally enforces one-second spacing.
[Rate limiting](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting).

Core metadata is CC0; supplementary data has a separate noncommercial/share-alike
license. This adapter maps core identity/catalog fields only.
[Data licenses](https://musicbrainz.org/doc/About/Data_License).
Some direct documentation fetches returned 429; the official indexed API/license
text and successfully retrieved rate-limit page supplied verification. No rate
limit was bypassed.

## Spotify

The Developer Policy prohibits analysis of Spotify content and ingestion into AI
models. Applying that restriction to LabelOS A&R research, this implementation
declares no supported capabilities and performs no Spotify requests.
[Developer Policy, III.13–14](https://developer.spotify.com/policy).

The February 2026 development-mode changes remove artist followers/popularity and
other endpoints/fields. The adapter does not assume these legacy features exist.
[February changelog](https://developer.spotify.com/documentation/web-api/references/changes/february-2026).

The official API normally uses OAuth access tokens, including client credentials
for app-only reads. Rate limits depend on app quota mode and a rolling 30-second
window; no universal request count is promised.
[Client credentials](https://developer.spotify.com/documentation/web-api/tutorials/client-credentials-flow),
[rate limits](https://developer.spotify.com/documentation/web-api/concepts/rate-limits).
Neither credentials nor a local approval reference override the blocked policy.

## YouTube

Only Data API v3 `search.list` (`type=channel`) and `channels.list`
(`part=snippet,statistics`) are used. A project API key accesses public data; owner
OAuth/Analytics scopes are not requested. Channels are not automatically musicians.
[Search](https://developers.google.com/youtube/v3/docs/search/list),
[channels.list](https://developers.google.com/youtube/v3/docs/channels/list).

Channel statistics expose views, subscribers and public video counts. Hidden
subscribers are omitted; visible subscribers are rounded to three significant
figures. Counts remain integers without float conversion.
[Channel resource](https://developers.google.com/youtube/v3/docs/channels).

The quota calculator, updated October 8, 2026, documents a separate default
100-calls/day search bucket at one unit per call and one unit for channels.list;
other calls share the project's general daily allocation. Endpoint pages may
still describe the older search cost. Use the project's actual current allocation,
not a hard-coded assumption that all quotas are fungible.
[Quota calculator](https://developers.google.com/youtube/v3/determine_quota_cost).

Non-authorized API data has a 30-day retention limit; statistics cannot be kept
longer without owner authorization. Policies restrict derived metrics and
cross-owner aggregation. The implementation attaches expiry and display-use
metadata; it does not calculate scores or persist data. API documentation's CC BY
license is not a license to redistribute YouTube API content.
[Developer policies, III.E](https://developers.google.com/youtube/terms/developer-policies).

## SoundCloud

The current OpenAPI specifies GET `/users`, `/users/{user_urn}` and
`/users/{user_urn}/tracks`, with URNs replacing assumptions about numeric path IDs.
Linked pagination supplies a collection and next URL; maximum page size is 200.
[Official OpenAPI](https://developers.soundcloud.com/docs/api/explorer/api.json).

Registered apps obtain OAuth tokens; app client credentials can access public
resources. Requests use `Authorization: OAuth <token>`. Tokens expire in roughly
one hour; refreshing is external to the adapter. No client-ID-only/private website
API fallback is supported.
[API guide](https://developers.soundcloud.com/docs/api/guide).

The published stream quota (15,000/24h) does not apply to these metadata methods.
The docs currently report no aggregate global cap; this is not a guarantee of
unlimited service. Token grants have separate app/IP limits, and 429 must be honored.
[Rate limits](https://developers.soundcloud.com/docs/api/rate-limits).

Commercial use is limited to specified cases or case-by-case approval. General A&R
use is therefore approval-gated. Standard terms permit only session caching of
User Content and require source/uploader credit and backlinks. Public visibility
does not waive those conditions.
[Terms](https://developers.soundcloud.com/docs/api/terms-of-use).

## Last.fm

GET `artist.search` and `artist.getInfo` use the HTTPS 2.0 endpoint with an API key;
no user session or signed write request is required. Search uses page/limit;
getInfo supports names/MBIDs and optional autocorrection (disabled here).
The official sample spells cumulative plays `plays`; the adapter also accepts
the JSON `playcount` spelling. Error 29 signals rate limiting; 10/26 indicate
invalid/suspended keys. No fixed global numeric read quota was verified.
[Search](https://www.last.fm/api/show/artist.search),
[artist info](https://www.last.fm/api/show/artist.getInfo).

Commercial and research use requires contacting Last.fm, with commercial use
subject to permission/terms. Attribution and links are required; data may not be
sublicensed. An API key alone is insufficient evidence for LabelOS's use.
[Terms](https://www.last.fm/api/tos).

## Songkick

API access requires a paid partnership/license; the public developer page does not
offer unrestricted hobbyist access. The adapter requires a license reference and
API key.
[Access](https://www.songkick.com/developer),
[key and pagination guide](https://www.songkick.com/developer/getting-started).

Implemented GET `/api/3.0/search/artists.json` accepts `apikey`, `query`, `page`
and `per_page` (maximum 50). Results contain provider ID, display name, public URI
and optional on-tour date. There is no invented catalog/streaming metric endpoint.
[Artist search](https://www.songkick.com/developer/artist-search).

Terms restrict access to approved licensees and allow rate limits. No universal
numeric quota is published in the reviewed material; the partnership's limits and
attribution/storage obligations control deployment.
[API terms](https://www.songkick.com/developer/api-terms-of-use).

## Approved public web research: Wikidata

The only implemented web source is an explicitly approved Wikidata entity JSON
lookup at `https://www.wikidata.org/wiki/Special:EntityData/{QID}.json`. The official
data access guide documents this interface, CC0 structured data, descriptive
User-Agents and honoring 429/Retry-After. It links changing global rate policies;
the adapter uses conservative local pacing rather than claiming an unlimited or
fixed provider quota. No authentication is required. English labels and
nondeprecated P434 artist-ID evidence are required by this narrow adapter.
[Data access and etiquette](https://www.wikidata.org/wiki/Wikidata:Data_access).

No other public web domain has been approved by this implementation. Adding one
requires its own documented authorized API, mapping, policy review and fixtures.
