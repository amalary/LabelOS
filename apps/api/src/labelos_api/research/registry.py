"""Optional composition and independent search fan-out. No startup registration."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from labelos_api.research.adapters import (
    LastFMAdapter,
    MusicBrainzAdapter,
    SongkickAdapter,
    SoundCloudAdapter,
    SpotifyAdapter,
    WikidataAdapter,
    YouTubeAdapter,
)
from labelos_api.research.adapters.common import AccessPolicy, HTTPAdapter, RequestGate
from labelos_api.research.contracts import (
    ArtistSearchRequest,
    ArtistSearchResponse,
    CollectionContext,
    ProviderConfiguration,
    ProviderDescriptor,
)
from labelos_api.research.errors import ProviderError, ProviderFailure
from labelos_api.research.providers import ProviderClient
from labelos_api.services.credential_store import CredentialStore

ADAPTERS: tuple[type[HTTPAdapter], ...] = (
    MusicBrainzAdapter,
    SpotifyAdapter,
    YouTubeAdapter,
    SoundCloudAdapter,
    LastFMAdapter,
    SongkickAdapter,
    WikidataAdapter,
)


@dataclass(frozen=True)
class ProviderAvailability:
    descriptor: ProviderDescriptor
    status: str
    metric_keys: tuple[str, ...]


class ProviderSuite:
    def __init__(
        self,
        configurations: Mapping[str, ProviderConfiguration],
        *,
        credential_store: CredentialStore | None = None,
        policies: Mapping[str, AccessPolicy] | None = None,
        transports: Mapping[str, httpx.AsyncBaseTransport] | None = None,
        gate: RequestGate | None = None,
    ):
        self.clients: dict[str, ProviderClient] = {}
        self.availability: dict[str, ProviderAvailability] = {}
        for adapter_type in ADAPTERS:
            key = adapter_type.descriptor.key
            adapter = adapter_type(
                policy=(policies or {}).get(key),
                transport=(transports or {}).get(key),
                gate=gate,
            )
            configuration = configurations.get(key)
            status = adapter.blocked_reason or "configured"
            if status == "configured":
                if configuration is None:
                    status = "not_configured"
                elif configuration.provider_key != key:
                    status = "invalid_configuration"
                elif adapter.descriptor.authentication.method != "none" and (
                    configuration.credential_ref is None or credential_store is None
                ):
                    status = "missing_credentials"
            self.availability[key] = ProviderAvailability(
                adapter.descriptor, status, tuple(adapter.metrics)
            )
            if status == "configured" and configuration is not None:
                self.clients[key] = ProviderClient(
                    adapter, configuration, credential_store=credential_store
                )

    async def search_artists(
        self,
        query: str,
        contexts: Mapping[str, CollectionContext],
        *,
        limit: int = 20,
    ) -> dict[str, ArtistSearchResponse | ProviderFailure]:
        """Failures are values per provider. Cancellation still propagates.

        The result does not join identities, score artists, or aggregate metrics.
        Skipped providers retain their explicit state in `availability`.
        """

        async def search(key: str, client: ProviderClient):
            request = ArtistSearchRequest(
                query=query, limit=min(limit, client.descriptor.max_page_size)
            )
            try:
                return key, await client.search_artists(request, context=contexts[key])
            except ProviderError as error:
                return key, error.failure

        return dict(
            await asyncio.gather(
                *(
                    search(key, client)
                    for key, client in self.clients.items()
                    if key in contexts
                    and "search_artists" in client.descriptor.capabilities
                )
            )
        )
