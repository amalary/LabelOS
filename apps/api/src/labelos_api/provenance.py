"""Record-level lineage contracts. Never accept provider payloads or URLs."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from labelos_api.governance import Contract

RecordKind = Literal["raw_source", "normalized_artist", "observation", "derived_output"]
TransformationType = Literal["normalize", "transform", "derive", "merge"]


class RawRecordCreate(Contract):
    version_id: UUID
    collection_run_id: UUID
    source_reference: UUID
    content_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class OutputRecord(Contract):
    kind: Literal["normalized_artist", "observation", "derived_output"]
    artist_id: UUID | None = None
    observation_id: UUID | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def binding(self):
        if (self.kind == "normalized_artist") != (self.artist_id is not None):
            raise ValueError("Only normalized artist snapshots require artist_id")
        if self.observation_id is not None and self.kind != "observation":
            raise ValueError("observation_id requires an observation output")
        return self


class RecordTransformationCreate(Contract):
    transformation_type: TransformationType
    transformation_version: str = Field(min_length=1, max_length=160)
    version_id: UUID
    collection_run_id: UUID | None = None
    input_ids: list[UUID] = Field(min_length=1, max_length=100)
    outputs: list[OutputRecord] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def shape(self):
        if len(set(self.input_ids)) != len(self.input_ids):
            raise ValueError("Duplicate input references")
        expected = {
            "normalize": "normalized_artist",
            "merge": "normalized_artist",
            "transform": "observation",
            "derive": "derived_output",
        }[self.transformation_type]
        if any(output.kind != expected for output in self.outputs):
            raise ValueError("Output kind does not match transformation type")
        if self.transformation_type == "merge" and (
            len(self.input_ids) < 2 or len(self.outputs) != 1
        ):
            raise ValueError(
                "A merge requires multiple identities and one new snapshot"
            )
        return self


class ProvenanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime

    @field_serializer("created_at")
    def utc_timestamp(self, value):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class RecordResponse(ProvenanceResponse):
    kind: RecordKind
    version_id: UUID
    collection_run_id: UUID | None
    transformation_id: UUID | None
    artist_id: UUID | None
    observation_id: UUID | None
    generation: int
    source_reference: UUID | None = None
    content_sha256: str | None = None


class TransformationResponse(ProvenanceResponse):
    transformation_type: TransformationType
    transformation_version: str
    version_id: UUID
    collection_run_id: UUID | None
    actor_kind: str
    actor_key: str


class EdgeResponse(ProvenanceResponse):
    input_id: UUID
    output_id: UUID


class TransformationResult(BaseModel):
    transformation: TransformationResponse
    inputs: list[UUID]
    outputs: list[RecordResponse]


class ProvenanceGraph(BaseModel):
    root_id: UUID
    direction: Literal["ancestors", "descendants"]
    records: list[RecordResponse]
    edges: list[EdgeResponse]
    transformations: list[TransformationResponse]
    truncated: bool
