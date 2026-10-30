"""Dependency-injected read-only adapters, with no registration or live I/O.

The future collection service must authorize workspace/provider/run/version and
credential-reference ownership before constructing a client. This boundary checks
binding consistency; it does not replace database-backed authorization/governance.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

from labelos_api.research.contracts import (
    ArtistLookupRequest,
    ArtistLookupResponse,
    ArtistSearchRequest,
    ArtistSearchResponse,
    CatalogLookupRequest,
    CatalogLookupResponse,
    CollectionContext,
    Contract,
    ObservationsRequest,
    ObservationsResponse,
    Operation,
    PageRequest,
    ProviderConfiguration,
    ProviderDescriptor,
)
from labelos_api.research.errors import (
    AdapterFailure,
    ProviderError,
    ProviderErrorCode,
    ProviderFailure,
    normalize_failure,
)
from labelos_api.services.credential_store import CredentialPayload, CredentialStore


class ResearchProviderAdapter(Protocol):
    """Implement only declared operations; unsupported ones may raise AdapterFailure.

    Credentials are transient, redacted material. Never copy them into results,
    cursors, identifiers, logs or errors. Transports should be injectable, async,
    cancellation-cooperative and must not perform automatic retries here.
    """

    @property
    def descriptor(self) -> ProviderDescriptor: ...

    async def search_artists(
        self,
        request: ArtistSearchRequest,
        *,
        context: CollectionContext,
        credentials: CredentialPayload | None,
    ) -> ArtistSearchResponse: ...

    async def lookup_artist(
        self,
        request: ArtistLookupRequest,
        *,
        context: CollectionContext,
        credentials: CredentialPayload | None,
    ) -> ArtistLookupResponse: ...

    async def lookup_catalog(
        self,
        request: CatalogLookupRequest,
        *,
        context: CollectionContext,
        credentials: CredentialPayload | None,
    ) -> CatalogLookupResponse: ...

    async def observations(
        self,
        request: ObservationsRequest,
        *,
        context: CollectionContext,
        credentials: CredentialPayload | None,
    ) -> ObservationsResponse: ...


Response = TypeVar(
    "Response",
    ArtistLookupResponse,
    ArtistSearchResponse,
    CatalogLookupResponse,
    ObservationsResponse,
)


class ProviderClient:
    def __init__(
        self,
        adapter: ResearchProviderAdapter,
        configuration: ProviderConfiguration,
        *,
        credential_store: CredentialStore | None = None,
    ) -> None:
        self.adapter = adapter
        self.configuration = ProviderConfiguration.model_validate(configuration)
        self.descriptor = ProviderDescriptor.model_validate(adapter.descriptor)
        self.credential_store = credential_store
        if self.configuration.provider_key != self.descriptor.key:
            raise ValueError("Configuration and adapter provider keys must match")

    async def search_artists(
        self, request: ArtistSearchRequest, *, context: CollectionContext
    ) -> ArtistSearchResponse:
        return await self._call(
            "search_artists",
            request,
            context,
            ArtistSearchResponse,
            lambda credentials: self.adapter.search_artists(
                request, context=context, credentials=credentials
            ),
        )

    async def lookup_artist(
        self, request: ArtistLookupRequest, *, context: CollectionContext
    ) -> ArtistLookupResponse:
        return await self._call(
            "lookup_artist",
            request,
            context,
            ArtistLookupResponse,
            lambda credentials: self.adapter.lookup_artist(
                request, context=context, credentials=credentials
            ),
        )

    async def lookup_catalog(
        self, request: CatalogLookupRequest, *, context: CollectionContext
    ) -> CatalogLookupResponse:
        return await self._call(
            "lookup_catalog",
            request,
            context,
            CatalogLookupResponse,
            lambda credentials: self.adapter.lookup_catalog(
                request, context=context, credentials=credentials
            ),
        )

    async def observations(
        self, request: ObservationsRequest, *, context: CollectionContext
    ) -> ObservationsResponse:
        return await self._call(
            "observations",
            request,
            context,
            ObservationsResponse,
            lambda credentials: self.adapter.observations(
                request, context=context, credentials=credentials
            ),
        )

    def _preflight(
        self, operation: Operation, request: Contract, context: CollectionContext
    ) -> None:
        configuration = self.configuration
        if (
            context.workspace_id != configuration.workspace_id
            or context.provider_id != configuration.provider_id
            or context.provider_key != configuration.provider_key
        ):
            raise AdapterFailure(ProviderErrorCode.invalid_request)
        if operation not in self.descriptor.capabilities:
            raise AdapterFailure(ProviderErrorCode.unsupported_operation)
        request_type = {
            "search_artists": ArtistSearchRequest,
            "lookup_artist": ArtistLookupRequest,
            "lookup_catalog": CatalogLookupRequest,
            "observations": ObservationsRequest,
        }[operation]
        try:
            request_type.model_validate(request)
        except ValueError:
            raise AdapterFailure(ProviderErrorCode.invalid_request) from None
        if (
            isinstance(request, PageRequest)
            and request.limit > self.descriptor.max_page_size
        ):
            raise AdapterFailure(ProviderErrorCode.invalid_request)
        if (
            isinstance(request, CatalogLookupRequest)
            and request.resource not in self.descriptor.resources
        ):
            raise AdapterFailure(ProviderErrorCode.unsupported_operation)
        if (
            isinstance(request, ObservationsRequest)
            and request.subject.resource not in self.descriptor.resources
        ):
            raise AdapterFailure(ProviderErrorCode.unsupported_operation)

    async def _credentials(self) -> CredentialPayload | None:
        authentication = self.descriptor.authentication
        if authentication.method == "none":
            return None
        reference = self.configuration.credential_ref
        if reference is None or self.credential_store is None:
            raise AdapterFailure(ProviderErrorCode.authentication_failed)
        payload = await self.credential_store.get(reference)
        values = payload.expose()
        if any(
            not isinstance(values.get(key), str) or not values[key].strip()
            for key in authentication.required_fields
        ):
            raise AdapterFailure(ProviderErrorCode.authentication_failed)
        if authentication.required_scopes:
            scopes = values.get("granted_scopes")
            if (
                not isinstance(scopes, (list, tuple))
                or not all(isinstance(scope, str) for scope in scopes)
                or not set(authentication.required_scopes) <= set(scopes)
            ):
                raise AdapterFailure(ProviderErrorCode.authentication_failed)
        return payload

    async def _call(
        self,
        operation: Operation,
        request: Contract,
        context: CollectionContext,
        response_type: type[Response],
        invoke: Callable[[CredentialPayload | None], Awaitable[Response]],
    ) -> Response:
        # Validate caller context separately; invalid context cannot label a failure.
        context = CollectionContext.model_validate(context)
        try:
            self._preflight(operation, request, context)
            async with asyncio.timeout(self.configuration.timeout_seconds):
                response = await invoke(await self._credentials())
            if type(response) is not response_type:
                raise ValueError("Unexpected response type")
            response = response_type.model_validate(response)
            self._validate_response(request, context, response)
            return response
        except Exception as error:
            failure = ProviderFailure(
                context=context, operation=operation, details=normalize_failure(error)
            )
        # Raise outside the except block so the raw exception is not retained as
        # __context__ (HTTP exceptions can include credentials in URLs/headers).
        raise ProviderError(failure) from None

    def _validate_response(
        self, request: Contract, context: CollectionContext, response: Response
    ) -> None:
        if response.context != context:
            raise ValueError("Response belongs to a different collection")
        if isinstance(response, ArtistLookupResponse):
            if (
                not isinstance(request, ArtistLookupRequest)
                or response.artist.external_id != request.artist_id
            ):
                raise ValueError("Artist lookup identity mismatch")
            items = (response.artist,)
        else:
            if (
                not isinstance(request, PageRequest)
                or len(response.items) > request.limit
            ):
                raise ValueError("Page exceeds requested limit")
            if (
                response.next_cursor is not None
                and response.next_cursor == request.cursor
            ):
                raise ValueError("Pagination cursor did not advance")
            items = response.items
        for item in items:
            if item.provenance.context != context:
                raise ValueError("Record belongs to a different collection")
            if item.resource not in self.descriptor.resources:
                raise ValueError("Adapter returned an undeclared resource")
        if (
            isinstance(response, CatalogLookupResponse)
            and isinstance(request, CatalogLookupRequest)
            and any(
                item.resource != request.resource
                or request.artist_id not in item.artist_ids
                for item in response.items
            )
        ):
            raise ValueError("Catalog item does not match request")
        if (
            isinstance(response, ObservationsResponse)
            and isinstance(request, ObservationsRequest)
            and any(
                item.subject != request.subject
                or item.metric_key not in request.metric_keys
                or not request.start_at <= item.observed_at < request.end_at
                for item in response.items
            )
        ):
            raise ValueError("Observation does not match request")
