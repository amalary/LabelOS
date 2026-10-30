"""One approved public web source: Wikidata entity JSON. Never fetch user URLs."""

from labelos_api.research.adapters.common import (
    Code,
    HTTPAdapter,
    identifier,
    object_data,
    records,
    source_id,
)
from labelos_api.research.adapters.musicbrainz import MBID
from labelos_api.research.contracts import (
    ArtistLookupResponse,
    AuthenticationRequirements,
    NormalizedArtist,
    ProviderDescriptor,
)
from labelos_api.research.errors import AdapterFailure


class WikidataAdapter(HTTPAdapter):
    base_url = "https://www.wikidata.org/wiki/Special:EntityData/"
    license_url = "https://creativecommons.org/publicdomain/zero/1.0/"
    approval_required = True
    user_agent_required = True
    # Conservative local pacing; not a claim about Wikimedia's changing quotas.
    spacing = 1.0
    descriptor = ProviderDescriptor(
        key="web_research",
        display_name="Wikidata",
        adapter_version="1.0.0",
        capabilities=frozenset({"lookup_artist"}),
        resources=frozenset({"artist"}),
        authentication=AuthenticationRequirements(method="none"),
    )

    async def lookup_artist(self, request, *, context, credentials):
        qid = identifier(request.artist_id, r"Q[1-9][0-9]*")
        data = await self.get(f"{qid}.json", {}, credentials)
        entity = object_data(data["entities"]).get(qid)
        if not entity or "missing" in entity:
            raise AdapterFailure(Code.data_unavailable)
        entity = object_data(entity)
        if entity["id"] != qid:
            raise ValueError("Entity identity mismatch")
        # P434 is specifically a MusicBrainz artist ID. Do not label arbitrary
        # people, songs or articles as artists based on a free-text description.
        mbids = tuple(
            statement["mainsnak"]["datavalue"]["value"]
            for statement in records(
                object_data(entity.get("claims", {})).get("P434", [])
            )
            if statement.get("rank") != "deprecated"
            and object_data(statement["mainsnak"]).get("snaktype") == "value"
        )
        name = object_data(object_data(entity.get("labels", {})).get("en", {})).get(
            "value"
        )
        if not mbids or not name:
            raise AdapterFailure(Code.data_unavailable)
        for mbid in mbids:
            source_id(mbid, MBID)
        return ArtistLookupResponse(
            context=context,
            artist=NormalizedArtist(
                external_id=qid,
                name=name,
                provenance=self.provenance(
                    context,
                    f"https://www.wikidata.org/wiki/{qid}",
                    revision=entity["lastrevid"],
                    identity_evidence="P434_musicbrainz_artist_id",
                    **{f"mbid_{i}": mbid for i, mbid in enumerate(mbids)},
                ),
            ),
        )
