"""MusicBrainz core metadata only; no supplementary tags/ratings or audio."""

import re
from datetime import date

from labelos_api.research.adapters.common import (
    HTTPAdapter,
    identifier,
    number,
    offset,
    records,
    source_id,
)
from labelos_api.research.contracts import (
    ArtistLookupResponse,
    ArtistSearchResponse,
    AuthenticationRequirements,
    CatalogItem,
    CatalogLookupResponse,
    NormalizedArtist,
    ProviderDescriptor,
    RateLimit,
)

MBID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class MusicBrainzAdapter(HTTPAdapter):
    base_url = "https://musicbrainz.org/ws/2/"
    license_url = "https://creativecommons.org/publicdomain/zero/1.0/"
    approval_required = True
    user_agent_required = True
    spacing = 1.0
    descriptor = ProviderDescriptor(
        key="musicbrainz",
        display_name="MusicBrainz",
        adapter_version="1.0.0",
        capabilities=frozenset({"search_artists", "lookup_artist", "lookup_catalog"}),
        resources=frozenset({"artist", "release", "track"}),
        authentication=AuthenticationRequirements(method="none"),
        rate_limits=(RateLimit(requests=1, window_seconds=1, scope="provider"),),
        max_page_size=100,
    )

    def artist(self, data, context):
        artist_id = source_id(data["id"], MBID)
        return NormalizedArtist(
            external_id=artist_id,
            name=data["name"],
            provenance=self.provenance(
                context,
                f"https://musicbrainz.org/artist/{artist_id}",
                type=data.get("type"),
                country=data.get("country"),
                disambiguation=data.get("disambiguation"),
                sort_name=data.get("sort-name"),
            ),
        )

    async def search_artists(self, request, *, context, credentials):
        start = offset(request.cursor)
        # Quote Lucene special characters so a name stays a literal search.
        escaped = re.sub(r'([+\-!(){}\[\]^"~*?:\\/|&])', r"\\\1", request.query)
        data = await self.get(
            "artist/",
            {
                "query": f'artist:"{escaped}"',
                "fmt": "json",
                "limit": request.limit,
                "offset": start,
            },
            credentials,
        )
        total = number(data["count"])
        items = tuple(self.artist(row, context) for row in records(data["artists"]))
        return ArtistSearchResponse(
            context=context,
            items=items,
            next_cursor=(
                str(start + len(items))
                if items and start + len(items) < total
                else None
            ),
        )

    async def lookup_artist(self, request, *, context, credentials):
        artist_id = identifier(request.artist_id, MBID)
        data = await self.get(f"artist/{artist_id}", {"fmt": "json"}, credentials)
        return ArtistLookupResponse(context=context, artist=self.artist(data, context))

    async def lookup_catalog(self, request, *, context, credentials):
        artist_id = identifier(request.artist_id, MBID)
        start = offset(request.cursor)
        entity = "recording" if request.resource == "track" else "release"
        data = await self.get(
            entity,
            {
                "artist": artist_id,
                "fmt": "json",
                "inc": (
                    "artist-credits+isrcs"
                    if entity == "recording"
                    else "artist-credits"
                ),
                "limit": request.limit,
                "offset": start,
            },
            credentials,
        )
        items = []
        total = number(data[f"{entity}-count"])
        for row in records(data[f"{entity}s"]):
            external_id = source_id(row["id"], MBID)
            raw_date = row.get("date")
            released = (
                date.fromisoformat(raw_date)
                if raw_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date)
                else None
            )
            isrcs = row.get("isrcs", [])
            if not isinstance(isrcs, list):
                raise ValueError("Invalid ISRC list")
            for isrc in isrcs:
                source_id(isrc, r"[A-Z]{2}[A-Z0-9]{3}[0-9]{7}")
            items.append(
                CatalogItem(
                    resource=request.resource,
                    external_id=external_id,
                    title=row["title"],
                    artist_ids=tuple(
                        source_id(credit["artist"]["id"], MBID)
                        for credit in records(row["artist-credit"])
                    ),
                    release_date=released,
                    duration_ms=row.get("length") if entity == "recording" else None,
                    isrc=isrcs[0] if len(isrcs) == 1 else None,
                    provenance=self.provenance(
                        context,
                        f"https://musicbrainz.org/{entity}/{external_id}",
                        entity_type=entity,
                        date_precision=raw_date,
                        status=row.get("status"),
                        **{f"isrc_{i}": value for i, value in enumerate(isrcs)},
                    ),
                )
            )
        return CatalogLookupResponse(
            context=context,
            items=tuple(items),
            next_cursor=(
                str(start + len(items))
                if items and start + len(items) < total
                else None
            ),
        )
