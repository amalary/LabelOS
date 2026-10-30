"""Reusable adapter contract suite.

Subclass ResearchProviderContractTests and provide provider_case(scenario), which
returns (client, context) backed by a mocked transport for each named scenario.
No provider credentials, network access or database are needed.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from labelos_api.research.contracts import (
    ArtistLookupRequest,
    ArtistLookupResponse,
    ArtistSearchRequest,
    CatalogLookupRequest,
    ObservationsRequest,
    ResourceRef,
)
from labelos_api.research.errors import ProviderError, ProviderErrorCode

NOW = datetime(2026, 10, 13, tzinfo=UTC)
REQUESTS = {
    "search_artists": ArtistSearchRequest(query="Artist", limit=2),
    "lookup_artist": ArtistLookupRequest(artist_id="artist-1"),
    "lookup_catalog": CatalogLookupRequest(
        artist_id="artist-1", resource="track", limit=2
    ),
    "observations": ObservationsRequest(
        subject=ResourceRef(resource="artist", external_id="artist-1"),
        metric_keys=("followers",),
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(days=1),
        limit=2,
    ),
}


class ResearchProviderContractTests:
    def request_for(self, client, operation):
        """Override for provider-local ID, metric and catalog resource syntax."""
        return REQUESTS[operation]

    @pytest.mark.parametrize("operation", REQUESTS)
    def test_success_contract(self, provider_case, operation):
        client, context = provider_case("success")
        if operation not in client.descriptor.capabilities:
            with pytest.raises(ProviderError) as caught:
                asyncio.run(
                    getattr(client, operation)(
                        self.request_for(client, operation), context=context
                    )
                )
            assert (
                caught.value.failure.details.code
                == ProviderErrorCode.unsupported_operation
            )
            return
        result = asyncio.run(
            getattr(client, operation)(
                self.request_for(client, operation), context=context
            )
        )
        assert result.context == context
        items = (
            (result.artist,)
            if isinstance(result, ArtistLookupResponse)
            else result.items
        )
        assert items
        for item in items:
            assert item.provenance.context == context
            assert item.provenance.source_reference
            assert item.provenance.collected_at.tzinfo is not None
        assert "contract-secret" not in result.model_dump_json()

    @pytest.mark.parametrize("operation", REQUESTS)
    @pytest.mark.parametrize(
        "scenario, code",
        [
            ("malformed", ProviderErrorCode.malformed_data),
            ("authentication", ProviderErrorCode.authentication_failed),
            ("rate_limit", ProviderErrorCode.rate_limited),
        ],
    )
    def test_failure_contract(self, provider_case, operation, scenario, code):
        client, context = provider_case(scenario)
        if operation not in client.descriptor.capabilities:
            pytest.skip("Adapter does not declare this operation")
        with pytest.raises(ProviderError) as caught:
            asyncio.run(
                getattr(client, operation)(
                    self.request_for(client, operation), context=context
                )
            )
        error = caught.value
        assert error.failure.details.code == code
        assert error.failure.operation == operation
        assert error.failure.context == context
        assert "contract-secret" not in error.failure.model_dump_json() + repr(error)
        assert error.__context__ is None
        assert error.__cause__ is None
        if scenario == "rate_limit":
            assert error.failure.details.retry_after_seconds == 60
            assert error.failure.details.retryable
