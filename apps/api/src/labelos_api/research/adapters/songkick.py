"""Licensed Songkick artist search. Events have no Prompt 10 resource shape."""

from labelos_api.research.adapters.common import (
    Code,
    HTTPAdapter,
    number,
    object_data,
    offset,
    public_url,
    records,
)
from labelos_api.research.contracts import (
    ArtistSearchResponse,
    AuthenticationRequirements,
    NormalizedArtist,
    ProviderDescriptor,
)
from labelos_api.research.errors import AdapterFailure


class SongkickAdapter(HTTPAdapter):
    base_url = "https://api.songkick.com/api/3.0/"
    license_url = "https://www.songkick.com/developer/api-terms-of-use"
    approval_required = True
    descriptor = ProviderDescriptor(
        key="songkick",
        display_name="Songkick",
        adapter_version="1.0.0",
        capabilities=frozenset({"search_artists"}),
        resources=frozenset({"artist"}),
        authentication=AuthenticationRequirements(
            method="api_key", required_fields=("api_key",)
        ),
        max_page_size=50,
    )

    def api_error(self, data, response):
        if data["resultsPage"]["status"] != "ok":
            raise AdapterFailure(Code.data_unavailable)

    async def search_artists(self, request, *, context, credentials):
        page = offset(request.cursor, first=1)
        data = (
            await self.get(
                "search/artists.json",
                {"query": request.query, "page": page, "per_page": request.limit},
                credentials,
            )
        )["resultsPage"]
        total = number(data["totalEntries"])
        if number(data["page"]) != page or number(data["perPage"]) != request.limit:
            raise ValueError("Unexpected Songkick pagination")
        rows = (
            object_data(data["results"]).get("artist", [])
            if total == 0
            else data["results"]["artist"]
        )
        items = tuple(
            NormalizedArtist(
                external_id=str(number(row["id"])),
                name=row["displayName"],
                provenance=self.provenance(
                    context,
                    public_url(row["uri"], "www.songkick.com"),
                    on_tour_until=row.get("onTourUntil"),
                ),
            )
            for row in records(rows)
        )
        return ArtistSearchResponse(
            context=context,
            items=items,
            next_cursor=(
                str(page + 1) if items and page * request.limit < total else None
            ),
        )
