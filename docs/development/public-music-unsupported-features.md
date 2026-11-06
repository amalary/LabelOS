# Unsupported and blocked public music features

Status as of **2026-10-13**. Reasons and official sources are recorded in the
[verification ledger](public-music-provider-verification.md); configuration and
the implemented [capability matrix](public-music-providers.md) are separate from
live access availability.

| Provider    | Unsupported or blocked                                                                   | Reason / next prerequisite                                                                                                                                  |
| ----------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MusicBrainz | Live hosted API use without approval/contact                                             | Commercial hosted access arrangement must be recorded                                                                                                       |
| MusicBrainz | Followers, streams, monthly listeners, historical performance                            | Metadata API does not supply these audience counters                                                                                                        |
| MusicBrainz | Genres/tags/ratings, artwork, audio                                                      | Supplementary licensing and artwork rights are outside this core-metadata adapter                                                                           |
| Spotify     | All A&R adapter operations                                                               | Current policy prohibits analysis of its content; no credential or configuration toggle enables it                                                          |
| Spotify     | Legacy followers/popularity, recommendations/audio analysis assumptions                  | Restricted/removed API functionality is not treated as available; any future implementation needs a fresh official review and applicable permission         |
| YouTube     | Music catalog mapped from arbitrary videos, verified musical-artist identity             | Channels/videos do not establish those semantics                                                                                                            |
| YouTube     | Revenue, demographics, watch time, owner analytics                                       | Requires separate owner authorization and Analytics integration                                                                                             |
| YouTube     | A&R scoring, derived metrics, cross-owner aggregation, indefinite public-counter history | Restricted by developer policies; supplied snapshots are for compliant display only                                                                         |
| SoundCloud  | Live commercial discovery without approved use/token                                     | Commercial use and OAuth registration/access prerequisites                                                                                                  |
| SoundCloud  | Private/unlisted tracks, audio downloads, streams, account contact data                  | Deliberately excluded from public metadata integration                                                                                                      |
| SoundCloud  | Release catalog and historical counters                                                  | Not implemented; playlists are not automatically releases                                                                                                   |
| SoundCloud  | Durable retention under standard terms                                                   | Session-only metadata use; a separate licensed storage implementation would be needed                                                                       |
| Last.fm     | Live use without commercial/research approval/key                                        | Provider terms require an approved arrangement                                                                                                              |
| Last.fm     | Full catalog, monthly listeners, platform stream counts                                  | Top albums/tracks are not a complete catalog; scrobbles are not platform streams                                                                            |
| Songkick    | Live use without paid partnership/key                                                    | Restricted paid API access                                                                                                                                  |
| Songkick    | Artist lookup, events/gigography ingestion                                               | Initial adapter implements the verified artist-search endpoint only; Prompt 10 has no event resource, and events must not be mislabeled releases or metrics |
| Public web  | Arbitrary URLs, HTML crawling, search-engine scraping, news/article copying              | No authorized source-specific API and licensing approval supplied                                                                                           |
| Wikidata    | Entities without P434, missing English labels, generic artist search                     | Narrow evidence-based artist lookup only; no guessed classifications or cross-provider identity merges                                                      |

Shared exclusions: automatic retries, token acquisition/refresh, distributed quota
scheduling, data persistence, retention workers, cross-provider scores, live
credential verification at startup, and historical backfill. These adapters are a
tested read-only boundary for a future authorized collection service. Declared
operations return sanitized typed failures when provider access is missing or
revoked. Undeclared operations return `unsupported_operation`; failures do not
disable healthy providers.

No real provider calls were used as a test oracle, and no access was purchased or
credentials provisioned. All HTTP contract tests use synthetic fixtures.
