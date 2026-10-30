# Provider access requests

Prepared October 14, 2026. **Not sent.** These are local drafts, not drafts saved
in Gmail. Gmail is installed, but this session exposes no Gmail sending tool or
active browser session.

## Last.fm

To: partners@last.fm

Subject: API access and commercial-use inquiry - LabelOS

Hello Last.fm partnerships team,

I'm developing LabelOS, an early-stage software project that helps independent
music teams organize artist research and catalog information.

I'd like to use publicly available artist metadata and aggregate listener and play
counts through your official API within a commercial music research workflow.

Could you advise on eligibility, obtaining an API key, commercial-use approval or
licensing fees, and the applicable usage, attribution and storage requirements?
I'm happy to provide further details needed to assess the request.

Thank you,
LabelOS project

Contact verified in the [Last.fm API terms](https://www.last.fm/api/tos).

## MetaBrainz / MusicBrainz

To: support@metabrainz.org

Subject: Commercial MusicBrainz API access inquiry - LabelOS

Hello MetaBrainz team,

I'm developing LabelOS, an early-stage software project that helps independent
music teams organize artist research and catalog information.

I'd like to use MusicBrainz artist identifiers and release and recording metadata
through the official hosted API within a commercial music research workflow.

Could you advise on the appropriate commercial access arrangement, any account
setup or approval required, pricing, request limits, and attribution requirements?
I'm happy to provide further details needed to assess the request.

Thank you,
LabelOS project

Contact verified on the [MetaBrainz contact page](https://metabrainz.org/contact).
MusicBrainz public read endpoints do not ordinarily require an API key; this
request concerns the hosted service's commercial access arrangement.

## Providers with other access routes

| Provider                               | Next action                                                                                                                                                                                                                                            | Important limitation                                                                                                                                                                                                                                                                        |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| YouTube                                | Create a Google Cloud project, enable YouTube Data API v3, and create a server-side API key. Restrict it to the API and your server's egress IP where practical. See [getting started](https://developers.google.com/youtube/v3/getting-started).      | The implemented adapter reads public channel information. A key does not authorize private analytics or otherwise prohibited downstream uses.                                                                                                                                               |
| SoundCloud                             | Obtain Artist Pro, then register an application through the official [application registration instructions](https://developers.soundcloud.com/docs/api/register-app). Obtain a client ID and secret and exchange them for an OAuth access token.      | Registration requires Artist Pro. Confirm the commercial research use is permitted under the [API terms](https://developers.soundcloud.com/docs/api/terms-of-use); credentials alone do not establish permission. The adapter consumes an access token.                                     |
| Songkick                               | Submit the [API licensing inquiry form](https://support.songkick.com/hc/en-us/requests/new?ticket_form_id=360000526113) with your company details and intended use.                                                                                    | The form currently lists recurring licensing starting at $500 per month. Approval and a paid partnership are needed; do not assume access until agreed.                                                                                                                                     |
| Spotify                                | The normal credential route is the [developer application dashboard](https://developer.spotify.com/documentation/web-api/concepts/apps). First resolve whether the intended A&R use is permitted.                                                      | The current LabelOS adapter is deliberately blocked because of restrictions on analysis under the [developer policy](https://developer.spotify.com/policy). Creating an app or obtaining a key will not unblock it. Any applicable written permission requires a new implementation review. |
| Approved public web research: Wikidata | No API key is required for the implemented public entity-data route. Record internal approval for Wikidata and configure a real contact in the identifying User-Agent. See [Wikidata data access](https://www.wikidata.org/wiki/Wikidata:Data_access). | This approval is LabelOS configuration, not an application for permission from Wikidata. Other websites require separate source review and are not enabled by this adapter.                                                                                                                 |

## After access is approved

Keep provider responses and licensing records as the basis for each approval
reference. Provision keys and tokens through the existing credential store;
do not commit secrets or put them in this document. Then configure the provider
as described in [the provider configuration guide](public-music-providers.md).

Only enable capabilities covered by the provider's permission. Unconfigured or
blocked providers can remain disabled while healthy providers operate.
