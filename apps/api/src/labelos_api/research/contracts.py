"""Version-one, provider-neutral inputs and normalized research data.

External identifiers are provider-local, never LabelOS artist IDs. Source references
are opaque UUIDs compatible with provenance.RawRecordCreate, not source URLs.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

Text = Annotated[str, Field(min_length=1, max_length=500)]
Key = Annotated[str, Field(min_length=1, max_length=120)]
Resource = Literal["artist", "release", "track", "observation"]
Operation = Literal["search_artists", "lookup_artist", "lookup_catalog", "observations"]
AuthMethod = Literal["none", "api_key", "bearer", "oauth2"]


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


class AuthenticationRequirements(Contract):
    method: AuthMethod
    required_fields: tuple[Key, ...] = ()
    required_scopes: tuple[Key, ...] = ()

    @model_validator(mode="after")
    def shape(self):
        if self.method == "none" and (self.required_fields or self.required_scopes):
            raise ValueError("Unauthenticated providers cannot require credentials")
        if self.method != "none" and not self.required_fields:
            raise ValueError("Authenticated providers must name credential fields")
        return self


class RateLimit(Contract):
    """Declared limits, not a distributed limiter or a promise of available quota."""

    requests: int = Field(gt=0)
    window_seconds: int = Field(gt=0)
    scope: Literal["provider", "credential", "workspace"]
    operation: Operation | None = None


class ProviderDescriptor(Contract):
    contract_version: Literal[1] = 1
    key: Key
    display_name: Text
    adapter_version: Key
    capabilities: frozenset[Operation]
    resources: frozenset[Resource]
    authentication: AuthenticationRequirements
    rate_limits: tuple[RateLimit, ...] = ()
    max_page_size: int = Field(default=100, ge=1, le=500)

    @model_validator(mode="after")
    def coherent_capabilities(self):
        required = {
            "search_artists": {"artist"},
            "lookup_artist": {"artist"},
            "observations": {"observation"},
        }
        for operation, resources in required.items():
            if operation in self.capabilities and not resources <= self.resources:
                raise ValueError("Capability requires its normalized resource")
        if "lookup_catalog" in self.capabilities and not (
            {"release", "track"} & self.resources
        ):
            raise ValueError("Catalog lookup requires releases or tracks")
        if any(
            limit.operation is not None and limit.operation not in self.capabilities
            for limit in self.rate_limits
        ):
            raise ValueError("Rate limit references an unsupported capability")
        return self


class CollectionContext(Contract):
    workspace_id: UUID
    provider_id: UUID
    provider_key: Key
    collection_run_id: UUID
    dataset_version_id: UUID


class ProviderField(Contract):
    """Allowlisted provider facts, not an unbounded raw vendor payload."""

    key: Key
    value: Text


class SourceProvenance(Contract):
    context: CollectionContext
    source_reference: UUID
    collected_at: AwareDatetime
    source_url: Text | None = None
    attribution: Text | None = None
    license_url: Text | None = None
    provider_fields: tuple[ProviderField, ...] = Field(default=(), max_length=100)
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def public_sources(self):
        for value in (self.source_url, self.license_url):
            if value is None:
                continue
            url = urlsplit(value)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
            ):
                raise ValueError(
                    "Source links must be public HTTPS URLs without queries"
                )
        if self.expires_at is not None and self.expires_at <= self.collected_at:
            raise ValueError("Expiry must follow collection")
        return self


class ProviderConfiguration(Contract):
    """Persist only a reference produced by the existing credential store.

    memory:// is for tests/local development only. Production uses the existing
    Settings/build_credential_store policy requiring GCP Secret Manager.
    """

    workspace_id: UUID
    provider_id: UUID
    provider_key: Key
    credential_ref: str | None = Field(
        default=None,
        repr=False,
        pattern=(
            r"^(gcp-secret-manager://projects/[A-Za-z0-9_-]+/secrets/"
            r"[A-Za-z0-9_-]{1,255}|memory://credentials/[a-f0-9]{32})$"
        ),
    )
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)


class PageRequest(Contract):
    limit: int = Field(default=100, ge=1, le=500)
    cursor: Text | None = Field(default=None, repr=False)


class ArtistSearchRequest(PageRequest):
    query: Text


class ArtistLookupRequest(Contract):
    artist_id: Text


class CatalogLookupRequest(PageRequest):
    artist_id: Text
    resource: Literal["release", "track"]


class ResourceRef(Contract):
    resource: Literal["artist", "release", "track"]
    external_id: Text


class ObservationsRequest(PageRequest):
    subject: ResourceRef
    metric_keys: tuple[Key, ...] = Field(min_length=1, max_length=100)
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode="after")
    def ordered_range(self):
        if self.start_at >= self.end_at:
            raise ValueError("Observation interval must be nonempty: [start, end)")
        if len(set(self.metric_keys)) != len(self.metric_keys):
            raise ValueError("Metric keys must be unique")
        return self


class NormalizedArtist(Contract):
    resource: Literal["artist"] = "artist"
    external_id: Text
    name: Text
    genres: tuple[Text, ...] = ()
    provenance: SourceProvenance


class CatalogItem(Contract):
    resource: Literal["release", "track"]
    external_id: Text
    title: Text
    artist_ids: tuple[Text, ...] = Field(min_length=1)
    release_date: date | None = None
    isrc: str | None = Field(default=None, pattern=r"^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$")
    duration_ms: int | None = Field(default=None, ge=0)
    provenance: SourceProvenance

    @model_validator(mode="after")
    def recording_fields(self):
        if self.resource != "track" and (
            self.isrc is not None or self.duration_ms is not None
        ):
            raise ValueError("Recording fields require a track")
        return self


class NormalizedObservation(Contract):
    """Scalar metric values map to AnalyticsMetricValueType without coercion.

    Missing data is an error/empty page, never a synthetic zero. Units and metric
    semantics remain explicit; cross-provider equivalence is not implied.
    """

    resource: Literal["observation"] = "observation"
    subject: ResourceRef
    metric_key: Key
    value_type: Literal["integer", "decimal", "string", "boolean"]
    value: int | Decimal | str | bool
    unit: Key | None = None
    observed_at: AwareDatetime
    provenance: SourceProvenance

    @model_validator(mode="after")
    def typed_value(self):
        expected = {
            "integer": int,
            "decimal": Decimal,
            "string": str,
            "boolean": bool,
        }[self.value_type]
        if type(self.value) is not expected:
            raise ValueError("Metric value does not match value_type")
        return self


class ProviderPage[Record: (NormalizedArtist, CatalogItem, NormalizedObservation)](
    Contract
):
    """Each returned page, including empty pages, belongs to one collection run.

    None means the last page. Cursors are opaque, non-secret continuation tokens;
    adapters keep credential-bearing provider URLs in private state instead.
    """

    context: CollectionContext
    items: tuple[Record, ...] = Field(max_length=500)
    next_cursor: Text | None = Field(default=None, repr=False)


class ArtistLookupResponse(Contract):
    context: CollectionContext
    artist: NormalizedArtist


class ArtistSearchResponse(ProviderPage[NormalizedArtist]):
    pass


class CatalogLookupResponse(ProviderPage[CatalogItem]):
    pass


class ObservationsResponse(ProviderPage[NormalizedObservation]):
    pass
