import asyncio
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from labelos_api.provenance import RawRecordCreate
from labelos_api.research.contracts import (
    ArtistLookupResponse,
    ArtistSearchRequest,
    ArtistSearchResponse,
    AuthenticationRequirements,
    CatalogItem,
    CatalogLookupRequest,
    CatalogLookupResponse,
    CollectionContext,
    NormalizedArtist,
    NormalizedObservation,
    ObservationsResponse,
    ProviderConfiguration,
    ProviderDescriptor,
    RateLimit,
    SourceProvenance,
)
from labelos_api.research.errors import (
    AdapterFailure,
    ProviderError,
)
from labelos_api.research.errors import (
    ProviderErrorCode as Code,
)
from labelos_api.research.providers import ProviderClient
from labelos_api.services.credential_store import (
    CredentialPayload,
    InMemoryCredentialStore,
)
from research_provider_contracts import NOW, REQUESTS, ResearchProviderContractTests


def http_error(status, retry_after="60"):
    request = httpx.Request(
        "GET",
        "https://mock.invalid/artists?key=contract-secret",
        headers={"Authorization": "Bearer contract-secret"},
    )
    response = httpx.Response(
        status,
        request=request,
        headers={"Retry-After": retry_after},
        text="contract-secret",
    )
    return httpx.HTTPStatusError("contract-secret", request=request, response=response)


class MockResearchAdapter:
    descriptor = ProviderDescriptor(
        key="mock",
        display_name="Mock research",
        adapter_version="1",
        capabilities=frozenset(REQUESTS),
        resources=frozenset({"artist", "track", "release", "observation"}),
        authentication=AuthenticationRequirements(
            method="api_key", required_fields=("api_key",)
        ),
        rate_limits=(RateLimit(requests=60, window_seconds=60, scope="credential"),),
    )

    def __init__(self, scenario="success"):
        self.scenario = scenario
        self.calls = 0
        self.error = None
        self.transform = lambda response: response

    async def _read(self, context, credentials):
        self.calls += 1
        if credentials is not None:
            assert credentials.expose()["api_key"] == "contract-secret"
        if self.error is not None:
            raise self.error
        if self.scenario == "authentication":
            raise http_error(401)
        if self.scenario == "rate_limit":
            raise http_error(429)
        if self.scenario == "slow":
            await asyncio.sleep(1)
        return SourceProvenance(
            context=context, source_reference=uuid4(), collected_at=NOW
        )

    def _result(self, response):
        if self.scenario == "malformed":
            return {"raw": "contract-secret"}
        if self.scenario == "empty" and not isinstance(response, ArtistLookupResponse):
            return response.model_copy(update={"items": ()})
        return self.transform(response)

    async def search_artists(self, request, *, context, credentials):
        provenance = await self._read(context, credentials)
        return self._result(
            ArtistSearchResponse(
                context=context,
                items=(
                    NormalizedArtist(
                        external_id="artist-1", name="Artist", provenance=provenance
                    ),
                ),
            )
        )

    async def lookup_artist(self, request, *, context, credentials):
        provenance = await self._read(context, credentials)
        return self._result(
            ArtistLookupResponse(
                context=context,
                artist=NormalizedArtist(
                    external_id=request.artist_id, name="Artist", provenance=provenance
                ),
            )
        )

    async def lookup_catalog(self, request, *, context, credentials):
        provenance = await self._read(context, credentials)
        return self._result(
            CatalogLookupResponse(
                context=context,
                items=(
                    CatalogItem(
                        resource=request.resource,
                        external_id="track-1",
                        title="Song",
                        artist_ids=(request.artist_id,),
                        provenance=provenance,
                    ),
                ),
            )
        )

    async def observations(self, request, *, context, credentials):
        provenance = await self._read(context, credentials)
        return self._result(
            ObservationsResponse(
                context=context,
                items=(
                    NormalizedObservation(
                        subject=request.subject,
                        metric_key="followers",
                        value_type="integer",
                        value=123,
                        unit="count",
                        observed_at=NOW,
                        provenance=provenance,
                    ),
                ),
            )
        )


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Provider contract tests must not use the network")

    monkeypatch.setattr("socket.create_connection", fail)
    monkeypatch.setattr(httpx.Client, "send", fail)
    monkeypatch.setattr(httpx.AsyncClient, "send", fail)


@pytest.fixture
def provider_case():
    def factory(scenario):
        context = CollectionContext(
            workspace_id=uuid4(),
            provider_id=uuid4(),
            provider_key="mock",
            collection_run_id=uuid4(),
            dataset_version_id=uuid4(),
        )
        store = InMemoryCredentialStore()
        reference = asyncio.run(
            store.put(CredentialPayload({"api_key": "contract-secret"}))
        )
        configuration = ProviderConfiguration(
            workspace_id=context.workspace_id,
            provider_id=context.provider_id,
            provider_key=context.provider_key,
            credential_ref=reference,
        )
        return (
            ProviderClient(
                MockResearchAdapter(scenario), configuration, credential_store=store
            ),
            context,
        )

    return factory


class TestMockProviderContract(ResearchProviderContractTests):
    pass


def call(client, context, operation="search_artists", request=None):
    return asyncio.run(
        getattr(client, operation)(request or REQUESTS[operation], context=context)
    )


def assert_failure(client, context, code, operation="search_artists", request=None):
    with pytest.raises(ProviderError) as caught:
        call(client, context, operation, request)
    assert caught.value.failure.details.code == code
    assert "contract-secret" not in caught.value.failure.model_dump_json()
    assert caught.value.__context__ is None
    return caught.value.failure.details


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (403, Code.authentication_failed, False),
        (402, Code.quota_exceeded, False),
        (404, Code.data_unavailable, False),
        (410, Code.data_unavailable, False),
        (408, Code.timeout, True),
        (429, Code.rate_limited, True),
        (503, Code.provider_unavailable, True),
        (400, Code.invalid_request, False),
    ],
)
def test_http_failure_normalization(provider_case, status, code, retryable):
    client, context = provider_case("success")
    client.adapter.error = http_error(status)
    assert assert_failure(client, context, code).retryable is retryable
    assert client.adapter.calls == 1


@pytest.mark.parametrize(
    "error,code",
    [
        (TimeoutError("contract-secret"), Code.timeout),
        (httpx.ReadTimeout("contract-secret"), Code.timeout),
        (httpx.ConnectError("contract-secret"), Code.provider_unavailable),
        (ValueError("contract-secret"), Code.malformed_data),
        (RuntimeError("contract-secret"), Code.internal_error),
        (AdapterFailure(Code.quota_exceeded), Code.quota_exceeded),
        (AdapterFailure(Code.data_unavailable), Code.data_unavailable),
    ],
)
def test_transport_sdk_and_parse_failures(provider_case, error, code):
    client, context = provider_case("success")
    client.adapter.error = error
    assert_failure(client, context, code)


@pytest.mark.parametrize(
    "retry_after", ["-1", "contract-secret", "999999999999999999", "1.5"]
)
def test_invalid_retry_hints_are_discarded(provider_case, retry_after):
    client, context = provider_case("success")
    client.adapter.error = http_error(429, retry_after)
    assert (
        assert_failure(client, context, Code.rate_limited).retry_after_seconds is None
    )


def test_deadline_and_cancellation(provider_case):
    client, context = provider_case("slow")
    client.configuration = client.configuration.model_copy(
        update={"timeout_seconds": 0.01}
    )
    assert_failure(client, context, Code.timeout)
    client.adapter.error = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        call(client, context)


@pytest.mark.parametrize(
    "scenario",
    [
        "missing_ref",
        "missing_store",
        "not_found",
        "empty_key",
        "scopes",
        "store_unavailable",
    ],
)
def test_credential_resolution(provider_case, scenario):
    client, context = provider_case("success")
    store = client.credential_store
    reference = client.configuration.credential_ref
    if scenario == "missing_ref":
        client.configuration = client.configuration.model_copy(
            update={"credential_ref": None}
        )
    elif scenario == "missing_store":
        client.credential_store = None
    elif scenario == "not_found":
        asyncio.run(store.delete(reference))
    elif scenario == "empty_key":
        asyncio.run(store.replace(reference, CredentialPayload({"api_key": " "})))
    elif scenario == "scopes":
        client.descriptor = client.descriptor.model_copy(
            update={
                "authentication": AuthenticationRequirements(
                    method="oauth2",
                    required_fields=("api_key",),
                    required_scopes=("read",),
                )
            }
        )
    else:
        store.fail_operations.add("get")
    code = (
        Code.provider_unavailable
        if scenario == "store_unavailable"
        else Code.authentication_failed
    )
    assert_failure(client, context, code)
    assert client.adapter.calls == 0


def test_no_auth_does_not_resolve_credentials(provider_case):
    client, context = provider_case("success")
    client.descriptor = client.descriptor.model_copy(
        update={"authentication": AuthenticationRequirements(method="none")}
    )
    client.credential_store.fail_operations.add("get")
    assert call(client, context).items


@pytest.mark.parametrize("field", ["workspace_id", "provider_id", "provider_key"])
def test_configuration_binding_checked_before_adapter(provider_case, field):
    client, context = provider_case("success")
    context = context.model_copy(
        update={field: "other" if field == "provider_key" else uuid4()}
    )
    assert_failure(client, context, Code.invalid_request)
    assert client.adapter.calls == 0


def test_unsupported_and_page_limits_do_not_call_adapter(provider_case):
    client, context = provider_case("success")
    client.descriptor = client.descriptor.model_copy(
        update={"capabilities": frozenset()}
    )
    assert_failure(client, context, Code.unsupported_operation)
    client.descriptor = client.adapter.descriptor
    assert_failure(
        client,
        context,
        Code.invalid_request,
        request=ArtistSearchRequest(query="x", limit=101),
    )
    assert client.adapter.calls == 0


@pytest.mark.parametrize(
    "field",
    [
        "workspace_id",
        "provider_id",
        "provider_key",
        "collection_run_id",
        "dataset_version_id",
    ],
)
@pytest.mark.parametrize("record_level", [True, False])
def test_cross_collection_results_rejected(provider_case, field, record_level):
    client, context = provider_case("success")
    other = context.model_copy(
        update={field: "other" if field == "provider_key" else uuid4()}
    )

    def transform(response):
        if not record_level:
            return response.model_copy(update={"context": other})
        item = response.items[0]
        provenance = item.provenance.model_copy(update={"context": other})
        return response.model_copy(
            update={"items": (item.model_copy(update={"provenance": provenance}),)}
        )

    client.adapter.transform = transform
    assert_failure(client, context, Code.malformed_data)


@pytest.mark.parametrize(
    "operation,update",
    [
        ("search_artists", {"name": " "}),
        ("lookup_artist", {"external_id": "wrong-artist"}),
        ("lookup_catalog", {"artist_ids": ("wrong-artist",)}),
        ("lookup_catalog", {"resource": "release"}),
        ("observations", {"metric_key": "unrequested"}),
        ("observations", {"observed_at": NOW + timedelta(days=1)}),
        ("observations", {"value": True}),
        ("observations", {"value_type": "decimal", "value": Decimal("NaN")}),
        ("observations", {"observed_at": NOW.replace(tzinfo=None)}),
    ],
)
def test_malformed_and_unrequested_records_rejected(provider_case, operation, update):
    client, context = provider_case("success")

    def transform(response):
        if isinstance(response, ArtistLookupResponse):
            return response.model_copy(
                update={"artist": response.artist.model_copy(update=update)}
            )
        return response.model_copy(
            update={"items": (response.items[0].model_copy(update=update),)}
        )

    client.adapter.transform = transform
    assert_failure(client, context, Code.malformed_data, operation)


def test_pagination_and_empty_success(provider_case):
    client, context = provider_case("empty")
    page = call(client, context)
    assert page.items == () and page.next_cursor is None
    client.adapter.scenario = "success"
    client.adapter.transform = lambda response: response.model_copy(
        update={"next_cursor": "page-2"}
    )
    assert call(client, context).next_cursor == "page-2"
    assert_failure(
        client,
        context,
        Code.malformed_data,
        request=ArtistSearchRequest(query="x", cursor="page-2"),
    )
    client.adapter.transform = lambda response: response.model_copy(
        update={"items": response.items * 3}
    )
    assert_failure(client, context, Code.malformed_data)


def test_reference_only_configuration_and_provenance_compatibility(provider_case):
    client, context = provider_case("success")
    assert (
        "contract-secret"
        not in repr(client.configuration) + client.configuration.model_dump_json()
    )
    for extra in (
        {"credential_ref": "contract-secret"},
        {"api_key": "contract-secret"},
    ):
        with pytest.raises(ValidationError):
            ProviderConfiguration.model_validate(
                {**client.configuration.model_dump(), **extra}
            )
    provenance = call(client, context).items[0].provenance
    record = RawRecordCreate(
        version_id=context.dataset_version_id,
        collection_run_id=context.collection_run_id,
        source_reference=provenance.source_reference,
    )
    assert record.collection_run_id == context.collection_run_id


def test_descriptor_rejects_inconsistent_capabilities():
    values = MockResearchAdapter.descriptor.model_dump()
    with pytest.raises(ValidationError):
        ProviderDescriptor.model_validate(
            {**values, "resources": frozenset({"artist"})}
        )
    with pytest.raises(ValidationError):
        RateLimit(requests=0, window_seconds=60, scope="credential")


@pytest.mark.parametrize(
    "value_type,value",
    [
        ("integer", 0),
        ("decimal", Decimal("1.25")),
        ("string", "rising"),
        ("boolean", False),
    ],
)
def test_scalar_values_and_wire_round_trip(provider_case, value_type, value):
    client, context = provider_case("success")
    client.adapter.transform = lambda response: response.model_copy(
        update={
            "items": (
                response.items[0].model_copy(
                    update={"value_type": value_type, "value": value}
                ),
            )
        }
    )
    response = call(client, context, "observations")
    decoded = ObservationsResponse.model_validate_json(response.model_dump_json())
    assert decoded == response
    assert type(decoded.items[0].value) is type(value)


def test_release_catalog_and_unsupported_resource(provider_case):
    client, context = provider_case("success")
    request = CatalogLookupRequest(artist_id="artist-1", resource="release")
    assert (
        call(client, context, "lookup_catalog", request).items[0].resource == "release"
    )
    client.descriptor = client.descriptor.model_copy(
        update={"resources": frozenset({"artist", "track", "observation"})}
    )
    assert_failure(
        client, context, Code.unsupported_operation, "lookup_catalog", request
    )
    assert client.adapter.calls == 1


def test_scoped_credentials_and_credential_deadline(provider_case):
    client, context = provider_case("success")
    client.descriptor = client.descriptor.model_copy(
        update={
            "authentication": AuthenticationRequirements(
                method="oauth2", required_fields=("api_key",), required_scopes=("read",)
            )
        }
    )
    asyncio.run(
        client.credential_store.replace(
            client.configuration.credential_ref,
            CredentialPayload(
                {"api_key": "contract-secret", "granted_scopes": ["read"]}
            ),
        )
    )
    assert call(client, context).items

    class SlowStore(InMemoryCredentialStore):
        async def get(self, credential_ref):
            await asyncio.sleep(1)
            return CredentialPayload({"api_key": "contract-secret"})

    client.credential_store = SlowStore()
    client.configuration = client.configuration.model_copy(
        update={"timeout_seconds": 0.01}
    )
    assert_failure(client, context, Code.timeout)
    assert client.adapter.calls == 1


def test_malformed_adapter_failure_is_safe(provider_case):
    client, context = provider_case("success")
    error = AdapterFailure(Code.rate_limited)
    error.details = error.details.model_copy(
        update={"retry_after_seconds": "contract-secret"}
    )
    client.adapter.error = error
    assert_failure(client, context, Code.malformed_data)


def test_request_validation_precedes_adapter(provider_case):
    client, context = provider_case("success")
    request = REQUESTS["observations"].model_copy(
        update={"end_at": NOW - timedelta(days=2)}
    )
    assert_failure(client, context, Code.invalid_request, "observations", request)
    assert client.adapter.calls == 0
