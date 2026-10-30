"""Small, read-only HTTP boundary. No retries, crawling or token exchanges."""

import json
import math
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid5

import httpx

from labelos_api.research.contracts import (
    ArtistLookupRequest,
    ArtistLookupResponse,
    ArtistSearchRequest,
    ArtistSearchResponse,
    CatalogLookupRequest,
    CatalogLookupResponse,
    CollectionContext,
    Contract,
    NormalizedObservation,
    ObservationsRequest,
    ObservationsResponse,
    ProviderDescriptor,
    ProviderField,
    SourceProvenance,
    Text,
)
from labelos_api.research.errors import AdapterFailure, ProviderErrorCode, _retry_after
from labelos_api.services.credential_store import CredentialPayload

Code = ProviderErrorCode


class AccessPolicy(Contract):
    """Non-secret reference to an actual approved use/license; never an API key."""

    approval_ref: Text | None = None
    user_agent: Text | None = None


class RequestGate:
    """Fail fast instead of sleeping. Share across adapters using the same egress.

    This process-local guard is not a distributed quota scheduler. Multi-process
    deployments must inject a shared egress limiter in their transport as well.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.deadlines: dict[str, float] = {}

    def enter(self, key: str, spacing: float) -> None:
        now = self.clock()
        remaining = self.deadlines.get(key, 0) - now
        if remaining > 0:
            raise AdapterFailure(
                Code.rate_limited, retry_after_seconds=math.ceil(remaining)
            )
        self.deadlines[key] = now + spacing

    def defer(self, key: str, seconds: int) -> None:
        self.deadlines[key] = max(self.deadlines.get(key, 0), self.clock() + seconds)


DEFAULT_GATE = RequestGate()


def identifier(value: str, pattern: str) -> str:
    if re.fullmatch(pattern, value) is None:
        raise AdapterFailure(Code.invalid_request)
    return quote(value, safe="")


def source_id(value: str, pattern: str) -> str:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError("Invalid provider identity")
    return quote(value, safe="")


def records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Expected a list of provider records")
    return value


def object_data(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected a provider object")
    return value


def number(value: Any) -> int:
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    raise ValueError("Invalid nonnegative integer")


def offset(cursor: str | None, *, first: int = 0) -> int:
    if cursor is None:
        return first
    if not re.fullmatch(r"[0-9]{1,9}", cursor) or int(cursor) < first:
        raise AdapterFailure(Code.invalid_request)
    return int(cursor)


def public_url(value: str, host: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or parsed.hostname != host:
        raise ValueError("Unexpected source URL")
    if parsed.username or parsed.password or parsed.port not in {None, 443, 80}:
        raise ValueError("Unexpected source URL")
    return urlunsplit(("https", host, parsed.path, "", ""))


class HTTPAdapter:
    descriptor: ProviderDescriptor
    base_url: str
    license_url: str
    approval_required = False
    user_agent_required = False
    spacing = 0.0
    retention_days: int | None = None
    metrics: dict[str, str] = {}

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        policy: AccessPolicy | None = None,
        gate: RequestGate | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.transport = transport
        self.policy = AccessPolicy.model_validate(policy or AccessPolicy())
        self.gate = gate or DEFAULT_GATE
        self.clock = clock

    @property
    def blocked_reason(self) -> str | None:
        if self.approval_required and not self.policy.approval_ref:
            return "approved_use_required"
        if self.user_agent_required and not self.policy.user_agent:
            return "identifying_user_agent_required"
        return None

    def check_access(self) -> None:
        if self.blocked_reason:
            raise AdapterFailure(Code.unsupported_operation)

    async def get(
        self, path: str, params: dict[str, Any], credentials: CredentialPayload | None
    ) -> dict[str, Any]:
        self.check_access()
        values = credentials.expose() if credentials else {}
        headers = {"Accept": "application/json"}
        if self.policy.user_agent:
            headers["User-Agent"] = self.policy.user_agent
        auth = self.descriptor.authentication
        for field in auth.required_fields:
            if not isinstance(values.get(field), str) or not values[field].strip():
                raise AdapterFailure(Code.authentication_failed)
        params = dict(params)
        if auth.method == "api_key":
            key = {"youtube": "key", "songkick": "apikey"}.get(
                self.descriptor.key, "api_key"
            )
            params[key] = values["api_key"]
        elif auth.method in {"oauth2", "bearer"}:
            headers["Authorization"] = f"OAuth {values['access_token']}"
        self.gate.enter(self.descriptor.key, self.spacing)
        # Use the async transport directly: AsyncClient logs query-bearing URLs
        # at INFO, which would expose API keys for these documented endpoints.
        # No redirects, proxy environment, cookies, retries or ambient auth.
        transport = self.transport or httpx.AsyncHTTPTransport(
            retries=0, trust_env=False
        )
        request = httpx.Request(
            "GET", self.base_url + path, params=params, headers=headers
        )
        try:
            response = await transport.handle_async_request(request)
            response.request = request
            try:
                await response.aread()
            finally:
                await response.aclose()
        finally:
            if self.transport is None:
                await transport.aclose()
        if response.status_code in {429, 503}:
            self.gate.defer(self.descriptor.key, _retry_after(response) or 1)
        self.http_error(response)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected JSON object")
        # Reject accidental upstream credential echoes even in allowlisted fields.
        body = json.dumps(data, ensure_ascii=False)
        if any(isinstance(v, str) and v and v in body for v in values.values()):
            raise ValueError("Credential echo in provider data")
        self.api_error(data, response)
        return data

    def http_error(self, response: httpx.Response) -> None:
        pass

    def api_error(self, data: dict[str, Any], response: httpx.Response) -> None:
        pass

    def provenance(
        self, context: CollectionContext, url: str, **fields: Any
    ) -> SourceProvenance:
        now = self.clock()
        if any(
            type(value) not in {str, int, bool, type(None)} for value in fields.values()
        ):
            raise ValueError("Provider facts must be scalar")
        return SourceProvenance(
            context=context,
            source_reference=uuid5(
                context.collection_run_id, f"{context.provider_key}:{url}"
            ),
            collected_at=now,
            source_url=url,
            attribution=self.descriptor.display_name,
            license_url=self.license_url,
            provider_fields=tuple(
                ProviderField(key=k, value=str(v))
                for k, v in fields.items()
                if v is not None and v != ""
            ),
            expires_at=(
                now + timedelta(days=self.retention_days)
                if self.retention_days
                else None
            ),
        )

    def check_observations(self, request: ObservationsRequest) -> None:
        self.check_access()
        if (
            request.subject.resource != "artist"
            or not set(request.metric_keys) <= self.metrics.keys()
        ):
            raise AdapterFailure(Code.unsupported_operation)
        if request.cursor or len(request.metric_keys) > request.limit:
            raise AdapterFailure(Code.invalid_request)
        if not request.start_at <= self.clock() < request.end_at:
            raise AdapterFailure(Code.data_unavailable)

    def snapshot(
        self,
        request: ObservationsRequest,
        context: CollectionContext,
        data: dict[str, Any],
        provenance: SourceProvenance,
    ) -> ObservationsResponse:
        if not isinstance(data, dict):
            raise ValueError("Expected a statistics object")
        if not request.start_at <= provenance.collected_at < request.end_at:
            raise AdapterFailure(Code.data_unavailable)
        return ObservationsResponse(
            context=context,
            items=tuple(
                NormalizedObservation(
                    subject=request.subject,
                    metric_key=key,
                    value_type="integer",
                    value=number(data[field]),
                    unit="count",
                    observed_at=provenance.collected_at,
                    provenance=provenance,
                )
                for key in request.metric_keys
                if (field := self.metrics[key]) in data and data[field] is not None
            ),
        )

    async def search_artists(
        self,
        request: ArtistSearchRequest,
        *,
        context: CollectionContext,
        credentials: CredentialPayload | None,
    ) -> ArtistSearchResponse:
        raise AdapterFailure(Code.unsupported_operation)

    async def lookup_artist(
        self,
        request: ArtistLookupRequest,
        *,
        context: CollectionContext,
        credentials: CredentialPayload | None,
    ) -> ArtistLookupResponse:
        raise AdapterFailure(Code.unsupported_operation)

    async def lookup_catalog(
        self,
        request: CatalogLookupRequest,
        *,
        context: CollectionContext,
        credentials: CredentialPayload | None,
    ) -> CatalogLookupResponse:
        raise AdapterFailure(Code.unsupported_operation)

    async def observations(
        self,
        request: ObservationsRequest,
        *,
        context: CollectionContext,
        credentials: CredentialPayload | None,
    ) -> ObservationsResponse:
        raise AdapterFailure(Code.unsupported_operation)
