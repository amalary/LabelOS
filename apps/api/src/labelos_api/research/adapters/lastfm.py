"""Last.fm named artist identities and cumulative scrobble counters."""

from urllib.parse import quote, unquote

from labelos_api.research.adapters.common import (
    Code,
    HTTPAdapter,
    number,
    offset,
    public_url,
    records,
)
from labelos_api.research.contracts import (
    ArtistLookupResponse,
    ArtistSearchResponse,
    AuthenticationRequirements,
    NormalizedArtist,
    ProviderDescriptor,
)
from labelos_api.research.errors import AdapterFailure, _retry_after


class LastFMAdapter(HTTPAdapter):
    base_url = "https://ws.audioscrobbler.com/2.0/"
    license_url = "https://www.last.fm/api/tos"
    approval_required = True
    metrics = {
        "lastfm.artist.listeners": "listeners",
        "lastfm.artist.playcount": "playcount",
    }
    descriptor = ProviderDescriptor(
        key="lastfm",
        display_name="Last.fm",
        adapter_version="1.0.0",
        capabilities=frozenset({"search_artists", "lookup_artist", "observations"}),
        resources=frozenset({"artist", "observation"}),
        authentication=AuthenticationRequirements(
            method="api_key", required_fields=("api_key",)
        ),
        max_page_size=100,
    )

    def api_error(self, data, response):
        if "error" in data:
            code = number(data["error"])
            mapped = {
                4: Code.authentication_failed,
                9: Code.authentication_failed,
                10: Code.authentication_failed,
                13: Code.authentication_failed,
                26: Code.authentication_failed,
                6: Code.data_unavailable,
                7: Code.data_unavailable,
                8: Code.provider_unavailable,
                11: Code.provider_unavailable,
                16: Code.provider_unavailable,
                29: Code.rate_limited,
            }.get(code, Code.invalid_request)
            retry = _retry_after(response) if mapped == Code.rate_limited else None
            if mapped == Code.rate_limited:
                self.gate.defer(self.descriptor.key, retry or 1)
            raise AdapterFailure(mapped, retry_after_seconds=retry)

    def artist(self, row, context):
        name = row["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Missing name")
        # MBID can be absent; keep one stable identity scheme for all records.
        external_id = "name:" + quote(name, safe="")
        return NormalizedArtist(
            external_id=external_id,
            name=name,
            provenance=self.provenance(
                context,
                public_url(row["url"], "www.last.fm"),
                mbid=row.get("mbid"),
                identity_scheme="lastfm_name",
                metric_semantics="cumulative_lastfm_scrobbles_not_streams",
            ),
        )

    async def search_artists(self, request, *, context, credentials):
        page = offset(request.cursor, first=1)
        data = (
            await self.get(
                "",
                {
                    "method": "artist.search",
                    "artist": request.query,
                    "format": "json",
                    "page": page,
                    "limit": request.limit,
                },
                credentials,
            )
        )["results"]
        items = tuple(
            self.artist(row, context)
            for row in records(data["artistmatches"]["artist"])
        )
        total = number(data["opensearch:totalResults"])
        start = number(data["opensearch:startIndex"])
        return ArtistSearchResponse(
            context=context,
            items=items,
            next_cursor=str(page + 1) if items and start + len(items) < total else None,
        )

    async def info(self, artist_id, credentials):
        if not artist_id.startswith("name:") or not artist_id[5:]:
            raise AdapterFailure(Code.invalid_request)
        name = unquote(artist_id[5:], errors="strict")
        if "name:" + quote(name, safe="") != artist_id:
            raise AdapterFailure(Code.invalid_request)
        row = (
            await self.get(
                "",
                {
                    "method": "artist.getInfo",
                    "artist": name,
                    "autocorrect": 0,
                    "format": "json",
                },
                credentials,
            )
        )["artist"]
        if row["name"] != name:
            raise AdapterFailure(Code.data_unavailable)
        return row

    async def lookup_artist(self, request, *, context, credentials):
        return ArtistLookupResponse(
            context=context,
            artist=self.artist(
                await self.info(request.artist_id, credentials), context
            ),
        )

    async def observations(self, request, *, context, credentials):
        self.check_observations(request)
        row = await self.info(request.subject.external_id, credentials)
        # The official example spells this counter `plays`; JSON deployments
        # also return `playcount`. Both represent the same Last.fm-only counter.
        stats = row["stats"]
        if isinstance(stats, dict) and "playcount" not in stats and "plays" in stats:
            stats = dict(stats, playcount=stats["plays"])
        return self.snapshot(
            request, context, stats, self.artist(row, context).provenance
        )
