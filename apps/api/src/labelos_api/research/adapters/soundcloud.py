"""Approved public SoundCloud user/track metadata. No playback/private data."""

from collections import OrderedDict
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from labelos_api.research.adapters.common import (
    Code,
    HTTPAdapter,
    identifier,
    public_url,
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
)
from labelos_api.research.errors import AdapterFailure

USER_URN = r"soundcloud:users:[0-9]+"
TRACK_URN = r"soundcloud:tracks:[0-9]+"


class SoundCloudAdapter(HTTPAdapter):
    base_url = "https://api.soundcloud.com/"
    license_url = "https://developers.soundcloud.com/docs/api/terms-of-use"
    approval_required = True
    metrics = {
        "soundcloud.user.followers": "followers_count",
        "soundcloud.user.tracks": "track_count",
    }
    descriptor = ProviderDescriptor(
        key="soundcloud",
        display_name="SoundCloud",
        adapter_version="1.0.0",
        capabilities=frozenset(
            {"search_artists", "lookup_artist", "lookup_catalog", "observations"}
        ),
        resources=frozenset({"artist", "track", "observation"}),
        authentication=AuthenticationRequirements(
            method="oauth2", required_fields=("access_token",)
        ),
        max_page_size=200,
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._cursors: OrderedDict[str, tuple[str, str]] = OrderedDict()

    def artist(self, row, context):
        source_id(row["urn"], USER_URN)
        return NormalizedArtist(
            external_id=row["urn"],
            name=row["username"],
            provenance=self.provenance(
                context,
                public_url(row["permalink_url"], "soundcloud.com"),
                entity_type="uploader_candidate",
                artist_identity="unverified",
                urn=row["urn"],
                retention="session_only",
                uploader=row["username"],
            ),
        )

    async def page(self, path, params, request, context, credentials):
        binding = (
            context.model_dump_json()
            + path
            + request.model_dump_json(exclude={"cursor"})
        )
        params = dict(params, limit=request.limit, linked_partitioning="true")
        current = None
        if request.cursor:
            stored = self._cursors.get(request.cursor)
            if not stored or stored[0] != binding:
                raise AdapterFailure(Code.invalid_request)
            current = stored[1]
            params["cursor"] = current
        data = await self.get(path, params, credentials)
        next_cursor = None
        href = data.get("next_href")
        if href is not None:
            if not isinstance(href, str) or not href:
                raise ValueError("Invalid pagination URL")
            url = urlsplit(href)
            if (
                url.scheme != "https"
                or url.netloc != "api.soundcloud.com"
                or unquote(url.path) != "/" + unquote(path)
                or url.fragment
            ):
                raise ValueError("Unexpected pagination target")
            values = parse_qs(url.query)
            cursors = values.get("cursor", [])
            if len(cursors) != 1 or not cursors[0] or cursors[0] == current:
                raise ValueError("Missing or nonadvancing pagination cursor")
            next_cursor = uuid4().hex
            self._cursors[next_cursor] = (binding, cursors[0])
            if len(self._cursors) > 128:
                self._cursors.popitem(last=False)
        return records(data["collection"]), next_cursor

    async def search_artists(self, request, *, context, credentials):
        rows, cursor = await self.page(
            "users", {"q": request.query}, request, context, credentials
        )
        return ArtistSearchResponse(
            context=context,
            items=tuple(self.artist(row, context) for row in rows),
            next_cursor=cursor,
        )

    async def user(self, artist_id, credentials):
        path_id = identifier(artist_id, USER_URN)
        row = await self.get(f"users/{path_id}", {}, credentials)
        if row["urn"] != artist_id:
            raise ValueError("User identity mismatch")
        return row

    async def lookup_artist(self, request, *, context, credentials):
        return ArtistLookupResponse(
            context=context,
            artist=self.artist(
                await self.user(request.artist_id, credentials), context
            ),
        )

    async def lookup_catalog(self, request, *, context, credentials):
        if request.resource != "track":
            raise AdapterFailure(Code.unsupported_operation)
        path_id = identifier(request.artist_id, USER_URN)
        rows, cursor = await self.page(
            f"users/{path_id}/tracks", {}, request, context, credentials
        )
        items = []
        for row in rows:
            # Even an owner token must not surface private content here.
            if row["sharing"] != "public":
                continue
            source_id(row["urn"], TRACK_URN)
            uploader = row["user"]
            source_id(uploader["urn"], USER_URN)
            items.append(
                CatalogItem(
                    resource="track",
                    external_id=row["urn"],
                    title=row["title"],
                    artist_ids=(uploader["urn"],),
                    duration_ms=row.get("duration"),
                    provenance=self.provenance(
                        context,
                        public_url(row["permalink_url"], "soundcloud.com"),
                        uploader=uploader["username"],
                        entity_type="uploaded_track",
                        urn=row["urn"],
                        metadata_artist=row.get("metadata_artist"),
                        genre=row.get("genre"),
                        track_license=row.get("license"),
                        retention="session_only",
                    ),
                )
            )
        return CatalogLookupResponse(
            context=context, items=tuple(items), next_cursor=cursor
        )

    async def observations(self, request, *, context, credentials):
        self.check_observations(request)
        row = await self.user(request.subject.external_id, credentials)
        return self.snapshot(
            request, context, row, self.artist(row, context).provenance
        )
