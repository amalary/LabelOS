"""Synthetic documented response shapes; all HTTP is mocked, no real secrets."""

import asyncio
import copy
import json
import logging
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from labelos_api.research.adapters.common import AccessPolicy, RequestGate
from labelos_api.research.contracts import (
    ArtistLookupRequest,
    ArtistSearchRequest,
    CatalogLookupRequest,
    CollectionContext,
    ObservationsRequest,
    ProviderConfiguration,
    ResourceRef,
    SourceProvenance,
)
from labelos_api.research.errors import (
    ProviderError,
    ProviderFailure,
)
from labelos_api.research.errors import (
    ProviderErrorCode as Code,
)
from labelos_api.research.providers import ProviderClient
from labelos_api.research.registry import ADAPTERS, ProviderSuite
from labelos_api.services.credential_store import (
    CredentialPayload,
    InMemoryCredentialStore,
)
from research_provider_contracts import NOW, ResearchProviderContractTests

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/research/providers.json").read_text()
)
TYPES = {cls.descriptor.key: cls for cls in ADAPTERS}
IDS = {
    "musicbrainz": "11111111-1111-4111-8111-111111111111",
    "youtube": "UCaaaaaaaaaaaaaaaaaaaaaa",
    "soundcloud": "soundcloud:users:123",
    "lastfm": "name:Fixture%20Artist",
    "songkick": "123",
    "web_research": "Q123",
    "spotify": "unsupported",
}
POLICY = AccessPolicy(
    approval_ref="test-only-approval",
    user_agent="LabelOS/1.0 (mailto:fixtures@example.test)",
)


def context_for(key):
    return CollectionContext(
        workspace_id=uuid4(),
        provider_id=uuid4(),
        provider_key=key,
        collection_run_id=uuid4(),
        dataset_version_id=uuid4(),
    )


def request_for(key, operation):
    if operation == "search_artists":
        return ArtistSearchRequest(query="Fixture Artist", limit=2)
    if operation == "lookup_artist":
        return ArtistLookupRequest(artist_id=IDS[key])
    if operation == "lookup_catalog":
        return CatalogLookupRequest(artist_id=IDS[key], resource="track", limit=2)
    return ObservationsRequest(
        subject=ResourceRef(resource="artist", external_id=IDS[key]),
        metric_keys=tuple(TYPES[key].metrics) or ("unsupported",),
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(days=1),
        limit=3,
    )


def response_body(key, request):
    params = request.url.params
    path = request.url.path
    if "query" in params or "q" in params or params.get("method") == "artist.search":
        operation = "search"
    elif path.endswith("/recording") or path.endswith("/tracks"):
        operation = "catalog"
    elif path.endswith("/release"):
        operation = "release"
    else:
        operation = "lookup"
    return copy.deepcopy(FIXTURES[key][operation])


def make_client(
    key, handler=None, *, scenario="success", policy=POLICY, gate=None, configured=True
):
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "GET"
        if handler:
            return handler(request)
        if scenario == "malformed":
            return httpx.Response(200, json={})
        if scenario == "authentication":
            return httpx.Response(401, json={"message": "contract-secret"})
        if scenario == "rate_limit":
            return httpx.Response(
                429, headers={"Retry-After": "60"}, json={"message": "contract-secret"}
            )
        return httpx.Response(200, json=response_body(key, request))

    adapter = TYPES[key](
        transport=httpx.MockTransport(respond),
        policy=policy,
        clock=lambda: NOW,
        gate=gate or RequestGate(),
    )
    context = context_for(key)
    store = InMemoryCredentialStore()
    ref = (
        asyncio.run(
            store.put(
                CredentialPayload(
                    {"api_key": "contract-secret", "access_token": "contract-secret"}
                )
            )
        )
        if configured
        else None
    )
    config = ProviderConfiguration(
        workspace_id=context.workspace_id,
        provider_id=context.provider_id,
        provider_key=key,
        credential_ref=ref,
    )
    return ProviderClient(adapter, config, credential_store=store), context, calls


def invoke(client, context, operation, request=None):
    return asyncio.run(
        getattr(client, operation)(
            request or request_for(context.provider_key, operation), context=context
        )
    )


@pytest.fixture(params=list(TYPES))
def provider_case(request):
    return lambda scenario: make_client(request.param, scenario=scenario)[:2]


class TestPublicMusicContracts(ResearchProviderContractTests):
    def request_for(self, client, operation):
        return request_for(client.descriptor.key, operation)


@pytest.mark.parametrize("key", [key for key in TYPES if key != "spotify"])
def test_attribution_and_source_fields(key):
    client, context, calls = make_client(key)
    operation = "search_artists" if key == "songkick" else "lookup_artist"
    result = invoke(client, context, operation)
    item = result.items[0] if operation == "search_artists" else result.artist
    assert item.provenance.source_url.startswith("https://")
    assert "?" not in item.provenance.source_url
    assert item.provenance.license_url.startswith("https://")
    assert item.provenance.attribution == client.descriptor.display_name
    assert item.provenance.provider_fields
    assert "contract-secret" not in result.model_dump_json()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "key", ["musicbrainz", "soundcloud", "lastfm", "songkick", "web_research"]
)
def test_approval_gate_prevents_io(key):
    client, context, calls = make_client(key, policy=AccessPolicy())
    op = "lookup_artist" if key == "web_research" else "search_artists"
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, op)
    assert caught.value.failure.details.code == Code.unsupported_operation
    assert not calls


@pytest.mark.parametrize("key", ["youtube", "lastfm", "songkick", "soundcloud"])
def test_missing_credentials_prevents_io(key):
    client, context, calls = make_client(key, configured=False)
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, "search_artists")
    assert caught.value.failure.details.code == Code.authentication_failed
    assert not calls


def test_spotify_cannot_be_enabled_with_an_approval_or_token():
    client, context, calls = make_client("spotify")
    assert client.adapter.blocked_reason == "policy_prohibits_content_analysis"
    with pytest.raises(ProviderError):
        invoke(client, context, "search_artists")
    assert not calls


@pytest.mark.parametrize("key", ["youtube", "lastfm", "soundcloud"])
def test_current_observations_are_not_fabricated_history(key):
    client, context, calls = make_client(key)
    request = request_for(key, "observations").model_copy(update={"end_at": NOW})
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, "observations", request)
    assert caught.value.failure.details.code == Code.data_unavailable
    assert not calls


@pytest.mark.parametrize("key", ["youtube", "lastfm", "soundcloud"])
def test_unsupported_metrics_rejected_before_io(key):
    client, context, calls = make_client(key)
    request = request_for(key, "observations").model_copy(
        update={"metric_keys": ("monthly_listeners",)}
    )
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, "observations", request)
    assert caught.value.failure.details.code == Code.unsupported_operation
    assert not calls


def test_youtube_hidden_counts_precision_and_retention():
    def handler(request):
        data = response_body("youtube", request)
        data["items"][0]["statistics"]["hiddenSubscriberCount"] = True
        return httpx.Response(200, json=data)

    client, context, _ = make_client("youtube", handler)
    result = invoke(client, context, "observations")
    metrics = {item.metric_key: item for item in result.items}
    assert "youtube.channel.subscribers" not in metrics
    assert metrics["youtube.channel.views"].value == 9007199254740993
    assert all(
        item.provenance.expires_at == NOW + timedelta(days=30) for item in result.items
    )


@pytest.mark.parametrize(
    "key,field", [("lastfm", "stats"), ("youtube", "statistics"), ("soundcloud", None)]
)
def test_missing_metrics_stay_missing(key, field):
    def handler(request):
        data = response_body(key, request)
        row = (
            data["artist"]
            if key == "lastfm"
            else data["items"][0] if key == "youtube" else data
        )
        if field:
            row[field] = {}
        else:
            row.pop("followers_count")
            row.pop("track_count")
        return httpx.Response(200, json=data)

    client, context, _ = make_client(key, handler)
    assert invoke(client, context, "observations").items == ()


@pytest.mark.parametrize("value", [True, -1, "NaN", "1.5", {}, []])
def test_bad_metric_values_fail_without_partial_page(value):
    def handler(request):
        data = response_body("lastfm", request)
        data["artist"]["stats"]["playcount"] = value
        return httpx.Response(200, json=data)

    client, context, _ = make_client("lastfm", handler)
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, "observations")
    assert caught.value.failure.details.code == Code.malformed_data


@pytest.mark.parametrize(
    "key,body,status,expected",
    [
        (
            "youtube",
            {"error": {"errors": [{"reason": "quotaExceeded"}]}},
            403,
            Code.quota_exceeded,
        ),
        (
            "youtube",
            {"error": {"errors": [{"reason": "userRateLimitExceeded"}]}},
            403,
            Code.rate_limited,
        ),
        (
            "youtube",
            {"error": {"errors": [{"reason": "keyInvalid"}]}},
            400,
            Code.authentication_failed,
        ),
        ("lastfm", {"error": 29}, 200, Code.rate_limited),
        ("lastfm", {"error": 26}, 200, Code.authentication_failed),
        ("lastfm", {"error": 11}, 200, Code.provider_unavailable),
        ("songkick", {"resultsPage": {"status": "error"}}, 200, Code.data_unavailable),
    ],
)
def test_vendor_error_translation(key, body, status, expected):
    client, context, calls = make_client(
        key, lambda r: httpx.Response(status, json=body, headers={"Retry-After": "60"})
    )
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, "search_artists")
    assert caught.value.failure.details.code == expected
    assert len(calls) == 1


def test_musicbrainz_partial_dates_and_recording_fields():
    client, context, calls = make_client("musicbrainz")
    request = request_for("musicbrainz", "lookup_catalog").model_copy(
        update={"resource": "release"}
    )
    release = invoke(client, context, "lookup_catalog", request).items[0]
    assert release.release_date is None
    assert {f.key: f.value for f in release.provenance.provider_fields}[
        "date_precision"
    ] == "2026-03"
    assert "genres" not in str(calls[0].url)
    client, context, _ = make_client("musicbrainz")
    track = invoke(client, context, "lookup_catalog").items[0]
    assert track.duration_ms == 182000
    assert track.isrc == "GBABC2600001"


def test_musicbrainz_pagination_advances_by_actual_page_length():
    clock = [10.0]
    gate = RequestGate(clock=lambda: clock[0])
    client, context, calls = make_client("musicbrainz", gate=gate)
    first = invoke(client, context, "lookup_catalog")
    assert first.next_cursor == "1"
    clock[0] += 1
    invoke(
        client,
        context,
        "lookup_catalog",
        request_for("musicbrainz", "lookup_catalog").model_copy(
            update={"cursor": first.next_cursor}
        ),
    )
    assert calls[-1].url.params["offset"] == "1"


def test_rate_gate_shared_across_instances_and_retry_after_honored():
    clock = [10.0]
    gate = RequestGate(clock=lambda: clock[0])
    client, context, calls = make_client(
        "musicbrainz", gate=gate, scenario="rate_limit"
    )
    with pytest.raises(ProviderError):
        invoke(client, context, "search_artists")
    other, other_context, other_calls = make_client("musicbrainz", gate=gate)
    clock[0] += 10
    with pytest.raises(ProviderError) as caught:
        invoke(other, other_context, "search_artists")
    assert caught.value.failure.details.retry_after_seconds == 50
    assert len(calls) == 1 and not other_calls


def test_soundcloud_cursor_is_private_bound_and_never_a_url():
    def handler(request):
        data = response_body("soundcloud", request)
        if request.url.params.get("cursor"):
            data["next_href"] = None
        return httpx.Response(200, json=data)

    client, context, calls = make_client("soundcloud", handler)
    first = invoke(client, context, "search_artists")
    assert "private-next-value" not in first.model_dump_json()
    assert len(first.next_cursor) == 32
    request = request_for("soundcloud", "search_artists").model_copy(
        update={"cursor": first.next_cursor}
    )
    assert invoke(client, context, "search_artists", request).next_cursor is None
    assert calls[-1].url.params["cursor"] == "private-next-value"
    with pytest.raises(ProviderError) as caught:
        invoke(
            client,
            context,
            "search_artists",
            request.model_copy(update={"query": "other"}),
        )
    assert caught.value.failure.details.code == Code.invalid_request
    assert len(calls) == 2


@pytest.mark.parametrize(
    "href",
    [
        "https://evil.test/users?cursor=x",
        "https://api.soundcloud.com/resolve?cursor=x",
        "https://api.soundcloud.com/users?client_id=secret",
        "http://api.soundcloud.com/users?cursor=x",
    ],
)
def test_soundcloud_rejects_unsafe_continuation(href):
    def handler(request):
        data = response_body("soundcloud", request)
        data["next_href"] = href
        return httpx.Response(200, json=data)

    client, context, calls = make_client("soundcloud", handler)
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, "search_artists")
    assert caught.value.failure.details.code == Code.malformed_data
    assert len(calls) == 1


def test_soundcloud_private_tracks_filtered_and_metadata_preserved():
    def handler(request):
        data = response_body("soundcloud", request)
        hidden = copy.deepcopy(data["collection"][0])
        hidden["sharing"] = "private"
        hidden["title"] = "hidden title"
        data["collection"].append(hidden)
        return httpx.Response(200, json=data)

    client, context, _ = make_client("soundcloud", handler)
    result = invoke(client, context, "lookup_catalog")
    assert len(result.items) == 1
    assert "hidden title" not in result.model_dump_json()
    assert "Fixture Guest" in result.model_dump_json()
    assert "session_only" in result.model_dump_json()
    assert "not-retained@example.test" not in result.model_dump_json()


def test_wikidata_rejects_arbitrary_entities_and_arbitrary_urls():
    body = copy.deepcopy(FIXTURES["web_research"]["lookup"])
    body["entities"]["Q123"]["claims"] = {}
    client, context, calls = make_client(
        "web_research", lambda r: httpx.Response(200, json=body)
    )
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, "lookup_artist")
    assert caught.value.failure.details.code == Code.data_unavailable
    with pytest.raises(ProviderError) as caught:
        invoke(
            client,
            context,
            "lookup_artist",
            ArtistLookupRequest(artist_id="https://127.0.0.1/private"),
        )
    assert caught.value.failure.details.code == Code.invalid_request
    assert len(calls) == 1


def test_no_redirects_or_credential_logs(caplog):
    caplog.set_level(logging.INFO)
    client, context, calls = make_client(
        "lastfm",
        lambda r: httpx.Response(302, headers={"Location": "https://evil.test/"}),
    )
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, "search_artists")
    assert len(calls) == 1
    assert "contract-secret" not in caplog.text + repr(caught.value)
    assert caught.value.__context__ is None


def test_credential_echo_in_normalized_field_rejected():
    body = copy.deepcopy(FIXTURES["lastfm"]["lookup"])
    body["artist"]["name"] = "contract-secret"
    client, context, _ = make_client("lastfm", lambda r: httpx.Response(200, json=body))
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, "lookup_artist")
    assert caught.value.failure.details.code == Code.malformed_data
    assert "contract-secret" not in repr(caught.value)


def test_suite_reports_blocked_missing_and_healthy_independently():
    good, good_context, _ = make_client("lastfm")
    missing, _, _ = make_client("youtube", configured=False)
    suite = ProviderSuite(
        {"lastfm": good.configuration, "youtube": missing.configuration},
        credential_store=good.credential_store,
        policies={"lastfm": POLICY},
        transports={
            "lastfm": httpx.MockTransport(
                lambda r: httpx.Response(200, json=response_body("lastfm", r))
            )
        },
    )
    assert suite.availability["spotify"].status == "policy_prohibits_content_analysis"
    assert suite.availability["youtube"].status == "missing_credentials"
    assert suite.availability["lastfm"].status == "configured"
    result = asyncio.run(
        suite.search_artists("Fixture Artist", {"lastfm": good_context}, limit=2)
    )
    assert result["lastfm"].items
    # A revoked key is discovered at call time and does not take down its peer.
    bad, bad_context, _ = make_client("youtube", scenario="authentication")
    suite.clients["youtube"] = bad
    result = asyncio.run(
        suite.search_artists(
            "Fixture Artist", {"lastfm": good_context, "youtube": bad_context}, limit=2
        )
    )
    assert result["lastfm"].items
    assert isinstance(result["youtube"], ProviderFailure)
    assert result["youtube"].details.code == Code.authentication_failed


@pytest.mark.parametrize(
    "key", ["musicbrainz", "youtube", "soundcloud", "lastfm", "songkick"]
)
def test_empty_search_is_success(key):
    bodies = {
        "musicbrainz": {"artists": [], "count": 0},
        "youtube": {"items": []},
        "soundcloud": {"collection": [], "next_href": None},
        "lastfm": {
            "results": {
                "artistmatches": {"artist": []},
                "opensearch:totalResults": "0",
                "opensearch:startIndex": "0",
            }
        },
        "songkick": {
            "resultsPage": {
                "status": "ok",
                "results": {},
                "page": 1,
                "perPage": 2,
                "totalEntries": 0,
            }
        },
    }
    client, context, _ = make_client(
        key, lambda r: httpx.Response(200, json=bodies[key])
    )
    result = invoke(client, context, "search_artists")
    assert result.items == () and result.next_cursor is None
    assert result.context == context


@pytest.mark.parametrize(
    "key,body",
    [
        ("musicbrainz", {"artists": {}, "count": 0}),
        ("youtube", {"items": {}}),
        ("soundcloud", {"collection": {}, "next_href": None}),
        (
            "lastfm",
            {
                "results": {
                    "artistmatches": {"artist": {}},
                    "opensearch:totalResults": "0",
                }
            },
        ),
        (
            "songkick",
            {
                "resultsPage": {
                    "status": "ok",
                    "results": [],
                    "page": 1,
                    "perPage": 2,
                    "totalEntries": 0,
                }
            },
        ),
        ("web_research", {"entities": []}),
    ],
)
def test_wrong_collection_shape_does_not_look_empty(key, body):
    client, context, _ = make_client(key, lambda r: httpx.Response(200, json=body))
    op = "lookup_artist" if key == "web_research" else "search_artists"
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, op)
    assert caught.value.failure.details.code == Code.malformed_data


@pytest.mark.parametrize(
    "key,param", [("lastfm", "page"), ("songkick", "page"), ("youtube", "pageToken")]
)
def test_page_continuation_parameters(key, param):
    def handler(request):
        data = response_body(key, request)
        if key == "songkick":
            data["resultsPage"]["page"] = int(request.url.params["page"])
        if key == "youtube" and param in request.url.params:
            data.pop("nextPageToken")
        return httpx.Response(200, json=data)

    client, context, calls = make_client(key, handler)
    result = invoke(client, context, "search_artists")
    invoke(
        client,
        context,
        "search_artists",
        request_for(key, "search_artists").model_copy(
            update={"cursor": result.next_cursor}
        ),
    )
    assert calls[-1].url.params[param] == result.next_cursor


@pytest.mark.parametrize(
    "key", ["musicbrainz", "youtube", "soundcloud", "lastfm", "songkick"]
)
def test_invalid_cursor_rejected_before_http(key):
    client, context, calls = make_client(key)
    with pytest.raises(ProviderError) as caught:
        invoke(
            client,
            context,
            "search_artists",
            request_for(key, "search_artists").model_copy(
                update={"cursor": "https://evil.test/"}
            ),
        )
    assert caught.value.failure.details.code == Code.invalid_request
    assert not calls


def test_musicbrainz_spacing_without_provider_throttling():
    gate = RequestGate(clock=lambda: 100.0)
    client, context, calls = make_client("musicbrainz", gate=gate)
    invoke(client, context, "lookup_artist")
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, "lookup_artist")
    assert caught.value.failure.details.code == Code.rate_limited
    assert caught.value.failure.details.retry_after_seconds == 1
    assert len(calls) == 1


@pytest.mark.parametrize("key", ["musicbrainz", "web_research"])
def test_identifying_user_agent_required(key):
    client, context, calls = make_client(
        key, policy=AccessPolicy(approval_ref="approval")
    )
    with pytest.raises(ProviderError):
        invoke(client, context, "lookup_artist")
    assert client.adapter.blocked_reason == "identifying_user_agent_required"
    assert not calls


def test_documented_lastfm_plays_alias_and_real_zero():
    body = copy.deepcopy(FIXTURES["lastfm"]["lookup"])
    body["artist"]["stats"] = {"listeners": "0", "plays": "123"}
    client, context, _ = make_client("lastfm", lambda r: httpx.Response(200, json=body))
    result = invoke(client, context, "observations")
    assert [item.value for item in result.items] == [0, 123]


def test_encoded_credential_echo_is_rejected():
    # The decoded name is the token, even though the wire representation is escaped.
    body = '{"artist":{"name":"\\u0063ontract-secret"}}'
    client, context, _ = make_client("lastfm", lambda r: httpx.Response(200, text=body))
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, "lookup_artist")
    assert caught.value.failure.details.code == Code.malformed_data


def test_soundcloud_authorization_and_urn_path():
    client, context, calls = make_client("soundcloud")
    invoke(client, context, "lookup_artist")
    assert calls[0].headers["Authorization"] == "OAuth contract-secret"
    assert calls[0].url.path == "/users/soundcloud:users:123"
    assert not calls[0].url.query


def test_async_transport_deadline_and_cancellation():
    async def run():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def handler(request):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        context = context_for("musicbrainz")
        adapter = TYPES["musicbrainz"](
            transport=httpx.MockTransport(handler), policy=POLICY, gate=RequestGate()
        )
        configuration = ProviderConfiguration(
            workspace_id=context.workspace_id,
            provider_id=context.provider_id,
            provider_key="musicbrainz",
            timeout_seconds=0.01,
        )
        client = ProviderClient(adapter, configuration)
        with pytest.raises(ProviderError) as caught:
            await client.lookup_artist(
                request_for("musicbrainz", "lookup_artist"), context=context
            )
        assert caught.value.failure.details.code == Code.timeout
        assert cancelled.is_set()
        adapter.gate = RequestGate()
        started.clear()
        task = asyncio.create_task(
            client.lookup_artist(
                request_for("musicbrainz", "lookup_artist"), context=context
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/",
        "https://user:secret@example.com/",
        "https://example.com/?key=secret",
        "https://example.com/#secret",
    ],
)
def test_provenance_disallows_credential_bearing_links(url):
    with pytest.raises(ValidationError):
        SourceProvenance(
            context=context_for("lastfm"),
            source_reference=uuid4(),
            collected_at=NOW,
            source_url=url,
        )


def test_provenance_expiry_and_json_roundtrip():
    client, context, _ = make_client("youtube")
    provenance = invoke(client, context, "lookup_artist").artist.provenance
    assert (
        SourceProvenance.model_validate_json(provenance.model_dump_json()) == provenance
    )
    with pytest.raises(ValidationError):
        SourceProvenance.model_validate(
            provenance.model_copy(update={"expires_at": NOW})
        )


@pytest.mark.parametrize(
    "field,value", [("id", "not-an-mbid"), ("country", {"raw": "payload"})]
)
def test_malformed_provider_facts_rejected(field, value):
    body = copy.deepcopy(FIXTURES["musicbrainz"]["lookup"])
    body[field] = value
    client, context, _ = make_client(
        "musicbrainz", lambda r: httpx.Response(200, json=body)
    )
    with pytest.raises(ProviderError) as caught:
        invoke(client, context, "lookup_artist")
    assert caught.value.failure.details.code == Code.malformed_data
