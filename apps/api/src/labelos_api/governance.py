"""Shared A&R / Analytics governance contracts inspired by Datasheets for Datasets.

Only documentation and non-sensitive provenance belong here. Provider records,
credentials, raw payloads and raw error messages belong outside these contracts.
"""

from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=4000)]
Key = Annotated[str, Field(min_length=1, max_length=120)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RetentionPolicy(Contract):
    raw_payload_policy: Literal["prohibited", "time_limited"] = "prohibited"
    raw_payload_days: int = Field(default=0, ge=0, le=36500)
    derived_data_days: int = Field(ge=1, le=36500)
    deletion_process: Text
    lineage_policy: Text

    @model_validator(mode="after")
    def raw_storage_is_explicit(self):
        if (self.raw_payload_policy == "prohibited") != (self.raw_payload_days == 0):
            raise ValueError(
                "Raw storage must be prohibited or explicitly time limited"
            )
        return self


class DatasetField(Contract):
    name: Key
    data_type: Key
    description: Text
    nullable: bool
    privacy_classification: Literal["non_personal", "personal", "sensitive"]


class DatasetSchema(Contract):
    description: Text
    fields: list[DatasetField] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_fields(self):
        names = [field.name for field in self.fields]
        if len(set(names)) != len(names):
            raise ValueError("Schema field names must be unique")
        return self


class Datasheet(Contract):
    schema_version: Literal[1] = 1
    motivation: Text | None = None
    composition: Text | None = None
    collection: Text | None = None
    preprocessing: Text | None = None
    intended_uses: list[Text] = Field(default_factory=list, max_length=50)
    prohibited_uses: list[Text] = Field(default_factory=list, max_length=50)
    limitations: Text | None = None
    distribution: Text | None = None
    licensing: Text | None = None
    terms_reference: Text | None = None
    terms_reviewed_on: date | None = None
    terms_valid_until: date | None = None
    license_approved: bool = False
    privacy: Text | None = None
    privacy_reviewed: bool = False
    retention: RetentionPolicy | None = None
    maintenance: Text | None = None
    maintainer: Text | None = None
    provenance: Text | None = None
    origin: Text | None = None
    source_version: Key | None = None
    ownership: Text | None = None
    coverage: Text | None = None
    update_frequency: Text | None = None
    biases: Text | None = None
    dataset_schema: DatasetSchema | None = None


def documentation_issues(document: Datasheet) -> list[str]:
    """Drafts may be partial; validation/publication requires a complete datasheet."""
    required = (
        "motivation",
        "composition",
        "collection",
        "preprocessing",
        "intended_uses",
        "limitations",
        "distribution",
        "licensing",
        "privacy",
        "retention",
        "maintenance",
        "maintainer",
        "provenance",
        "origin",
        "source_version",
        "ownership",
        "coverage",
        "update_frequency",
        "biases",
        "dataset_schema",
    )
    return [f"missing_{name}" for name in required if not getattr(document, name)]


class Eligibility(Contract):
    eligible: bool
    issues: list[str]


def validate_production(document: Datasheet, *, today: date) -> Eligibility:
    """Eligibility is time-sensitive; a historical approval is not a perpetual grant."""
    fields = (
        "motivation",
        "composition",
        "collection",
        "preprocessing",
        "intended_uses",
        "limitations",
        "distribution",
        "licensing",
        "terms_reference",
        "privacy",
        "retention",
        "maintenance",
        "maintainer",
    )
    issues = [f"missing_{name}" for name in fields if not getattr(document, name)]
    if not document.license_approved:
        issues.append("license_not_approved")
    if not document.privacy_reviewed:
        issues.append("privacy_not_reviewed")
    if document.terms_reviewed_on is None or document.terms_reviewed_on > today:
        issues.append("terms_review_required")
    if document.terms_valid_until is None or document.terms_valid_until < today:
        issues.append("terms_expired_or_unbounded")
    if (
        document.terms_reviewed_on
        and document.terms_valid_until
        and document.terms_valid_until < document.terms_reviewed_on
    ):
        issues.append("invalid_terms_review_period")
    return Eligibility(eligible=not issues, issues=issues)


class SourceRegistration(Contract):
    key: Key
    display_name: Annotated[str, Field(min_length=1, max_length=200)]
    provider_type: Annotated[str, Field(min_length=1, max_length=80)] = "internal"
    external_account_id: Annotated[str, Field(min_length=1, max_length=255)] | None = (
        None
    )


class SourceRecord(BaseModel):
    """Governance projection: provider metadata and credentials never cross here."""

    model_config = ConfigDict(from_attributes=True, frozen=True)
    id: UUID
    organization_id: UUID
    created_at: datetime
    key: str
    display_name: str
    provider_type: str
    external_account_id: str | None = None


class DatasetCreate(Contract):
    key: Annotated[str, Field(min_length=1, max_length=160)]
    display_name: Annotated[str, Field(min_length=1, max_length=200)]
    provider_id: UUID
    owner_department: Annotated[str, Field(min_length=1, max_length=80)]


class VersionCreate(Contract):
    version_key: Key
    schema_version: Key | None = None
    # SHA-256 of the actual dataset artifact, supplied by the collecting adapter.
    data_fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None
    collection_start: AwareDatetime | None = None
    collection_end: AwareDatetime | None = None
    source_references: (
        list[Annotated[str, Field(min_length=1, max_length=2000)]] | None
    ) = Field(default=None, min_length=1, max_length=100)
    parent_version_id: UUID | None = None

    @model_validator(mode="after")
    def valid_collection_window(self):
        if (self.collection_start is None) != (self.collection_end is None):
            raise ValueError("Both collection window boundaries are required")
        if self.collection_start is not None and self.collection_end is not None:
            if self.collection_end < self.collection_start:
                raise ValueError("Collection window ends before it starts")
            self.collection_start = self.collection_start.astimezone(UTC)
            self.collection_end = self.collection_end.astimezone(UTC)
        if self.source_references and len(set(self.source_references)) != len(
            self.source_references
        ):
            raise ValueError("Duplicate source references")
        return self


VersionState = Literal["draft", "finalized", "archived"]


class VersionTransition(Contract):
    expected_state: VersionState
    state: Literal["finalized", "archived"]


class DocumentationCreate(Contract):
    document: Datasheet
    change_reason: Annotated[str, Field(min_length=1, max_length=1000)]
    expected_revision: int = Field(ge=0)
    production_eligible: bool = False


DocumentationState = Literal["draft", "validated", "published"]


class DocumentationTransition(Contract):
    state: Literal["validated", "published"]
    expected_revision: int = Field(ge=1)
    change_reason: Annotated[str, Field(min_length=1, max_length=1000)]


class CollectionRunCreate(Contract):
    documentation_id: UUID
    run_key: Annotated[str, Field(min_length=1, max_length=160)]
    production: bool = False
    job_id: UUID | None = None
    retry_of_id: UUID | None = None
    max_attempts: int = Field(default=3, ge=1, le=20)
    not_before: AwareDatetime | None = None

    @model_validator(mode="after")
    def utc_retry_time(self):
        if self.not_before is not None:
            self.not_before = self.not_before.astimezone(UTC)
        return self


RunStatus = Literal[
    "queued",
    "running",
    "completed",
    "partially_completed",
    "failed",
    "cancelled",
    "succeeded",  # Historical API spelling remains supported.
]


class CollectionCheckpoint(Contract):
    """Safe resume coordinates; opaque provider cursors belong in a secret store."""

    offset: int = Field(default=0, ge=0, strict=True)
    page: int = Field(default=0, ge=0, strict=True)
    cursor_reference: UUID | None = None


class CollectionRunProgress(Contract):
    expected_revision: int = Field(ge=0)
    records_seen: int = Field(ge=0)
    records_written: int = Field(ge=0)
    records_rejected: int = Field(ge=0)
    checkpoint: CollectionCheckpoint

    @model_validator(mode="after")
    def consistent_counts(self):
        if self.records_written + self.records_rejected > self.records_seen:
            raise ValueError("Written and rejected counts exceed records seen")
        return self


class CollectionRunTransition(Contract):
    status: Literal[
        "running",
        "completed",
        "partially_completed",
        "succeeded",
        "failed",
        "cancelled",
    ]
    records_seen: int = Field(default=0, ge=0)
    records_written: int = Field(default=0, ge=0)
    records_rejected: int = Field(default=0, ge=0)
    error_code: (
        Literal[
            "provider_unavailable",
            "rate_limited",
            "access_denied",
            "invalid_data",
            "terms_changed",
            "internal_error",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def consistent_outcome(self):
        if self.records_written + self.records_rejected > self.records_seen:
            raise ValueError("Written and rejected counts exceed records seen")
        if (self.status in {"failed", "partially_completed"}) != (
            self.error_code is not None
        ):
            raise ValueError(
                "Failed and partially completed runs require an error code"
            )
        if self.status == "partially_completed" and not self.records_written:
            raise ValueError("Partial completion requires some written records")
        if self.status == "running" and self.records_seen:
            raise ValueError("Record counts are reported when a run finishes")
        return self


class TransformationCreate(Contract):
    output_version_id: UUID
    input_version_ids: list[UUID] = Field(min_length=1, max_length=100)
    collection_run_id: UUID | None = None
    name: Annotated[str, Field(min_length=1, max_length=160)]
    code_reference: Annotated[str, Field(min_length=1, max_length=255)]
    parameters_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None
    description: Annotated[str, Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def distinct_inputs(self):
        if len(set(self.input_version_ids)) != len(self.input_version_ids):
            raise ValueError("Duplicate lineage inputs")
        if self.output_version_id in self.input_version_ids:
            raise ValueError("A version cannot be its own input")
        return self
