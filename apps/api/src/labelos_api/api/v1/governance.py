"""Governance administration and department-neutral read interfaces."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from labelos_database.models import (
    AnalyticsProvider,
    CollectionRun,
    Dataset,
    DatasetDocumentation,
    DatasetLineage,
    DatasetTransformation,
    DatasetVersion,
    GovernanceActivity,
)
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from sqlalchemy.exc import IntegrityError

from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.governance import (
    CollectionCheckpoint,
    CollectionRunCreate,
    CollectionRunProgress,
    CollectionRunTransition,
    DatasetCreate,
    Datasheet,
    DocumentationCreate,
    DocumentationState,
    DocumentationTransition,
    Eligibility,
    RunStatus,
    SourceRegistration,
    TransformationCreate,
    VersionCreate,
    VersionState,
    VersionTransition,
)
from labelos_api.provenance import (
    ProvenanceGraph,
    RawRecordCreate,
    RecordTransformationCreate,
    TransformationResult,
)
from labelos_api.provenance import (
    RecordResponse as ProvenanceRecordResponse,
)
from labelos_api.services.governance_service import (
    GovernanceConflict,
    GovernanceError,
    GovernanceForbidden,
    GovernanceNotFound,
    GovernanceService,
)
from labelos_api.services.provenance_service import ProvenanceService

router = APIRouter(prefix="/workspaces/{workspace_id}/governance", tags=["governance"])


async def service(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
):
    """One transaction for state, permanent audit and outbox; never partial writes."""
    try:
        yield ProvenanceService(session, workspace_id, actor=context)
        await session.commit()
    except (GovernanceError, IntegrityError) as exc:
        await session.rollback()
        code = 400
        detail = str(exc)
        if isinstance(exc, GovernanceForbidden):
            code, detail = 403, "Insufficient governance permission"
        elif isinstance(exc, GovernanceNotFound):
            code = 404
        elif isinstance(exc, (GovernanceConflict, IntegrityError)):
            code, detail = 409, "Conflicting governance record or revision"
        raise HTTPException(code, detail) from exc
    except Exception:
        await session.rollback()
        raise


Service = Annotated[GovernanceService, Depends(service, scope="function")]
Provenance = Annotated[ProvenanceService, Depends(service, scope="function")]
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]


@router.post(
    "/provenance/records", response_model=ProvenanceRecordResponse, status_code=201
)
async def register_raw_record(payload: RawRecordCreate, service: Provenance):
    return await service.register_raw(payload)


@router.post(
    "/provenance/transformations", response_model=TransformationResult, status_code=201
)
async def transform_records(payload: RecordTransformationCreate, service: Provenance):
    return await service.transform(payload)


@router.get("/provenance/records", response_model=list[ProvenanceRecordResponse])
async def provenance_records(
    service: Provenance,
    artist_id: UUID | None = None,
    observation_id: UUID | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
):
    return await service.records(
        artist_id=artist_id, observation_id=observation_id, limit=limit, offset=offset
    )


@router.get("/provenance/records/{record_id}/lineage", response_model=ProvenanceGraph)
async def traverse_provenance(
    record_id: UUID,
    service: Provenance,
    direction: str = "ancestors",
    max_depth: Annotated[int, Query(ge=1, le=100)] = 50,
    max_nodes: Annotated[int, Query(ge=1, le=1000)] = 1000,
    include_source_details: bool = False,
):
    return await service.traverse(
        record_id,
        direction=direction,
        max_depth=max_depth,
        max_nodes=max_nodes,
        include_source_details=include_source_details,
    )


class RecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID = Field(validation_alias="organization_id")
    created_at: datetime


class SourceResponse(RecordResponse):
    key: str
    display_name: str
    provider_type: str
    external_account_id: str | None


class DatasetResponse(RecordResponse):
    key: str
    display_name: str
    provider_id: UUID
    owner_department: str


class VersionResponse(RecordResponse):
    dataset_id: UUID
    version_key: str
    schema_version: str | None
    data_fingerprint: str | None
    collection_start: datetime | None
    collection_end: datetime | None
    source_references: list[str] | None
    parent_version_id: UUID | None
    state: VersionState
    finalized_at: datetime | None
    archived_at: datetime | None

    @field_serializer(
        "created_at",
        "collection_start",
        "collection_end",
        "finalized_at",
        "archived_at",
    )
    def utc_timestamp(self, value: datetime | None):
        return (
            value.replace(tzinfo=UTC)
            if value is not None and value.tzinfo is None
            else value
        )


class DocumentationResponse(RecordResponse):
    version_id: UUID
    revision: int
    state: DocumentationState
    authored_revision: int | None
    document: Datasheet
    document_sha256: str
    production_eligible: bool
    change_reason: str
    actor_kind: str
    actor_key: str

    @field_serializer("created_at")
    def utc_timestamp(self, value: datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    @field_serializer("document")
    def stored_document(self, value: Datasheet):
        # New optional contract fields must not change historical digest inputs.
        return value.model_dump(mode="json", exclude_unset=True)


class RunResponse(RecordResponse):
    documentation_id: UUID
    source_id: UUID
    version_id: UUID
    run_key: str
    job_id: UUID | None
    retry_of_id: UUID | None
    attempt: int
    max_attempts: int
    not_before: datetime | None
    checkpoint: CollectionCheckpoint | None
    progress_revision: int
    production: bool
    status: RunStatus
    started_at: datetime | None
    completed_at: datetime | None
    records_seen: int
    records_written: int
    records_rejected: int
    error_code: str | None

    @field_serializer("created_at", "started_at", "completed_at", "not_before")
    def utc_timestamp(self, value: datetime | None):
        return (
            value.replace(tzinfo=UTC)
            if value is not None and value.tzinfo is None
            else value
        )


class TransformationResponse(RecordResponse):
    output_version_id: UUID
    collection_run_id: UUID | None
    name: str
    code_reference: str
    parameters_sha256: str | None
    description: str


class LineageResponse(RecordResponse):
    transformation_id: UUID
    input_version_id: UUID


class ActivityResponse(RecordResponse):
    action: str
    entity_id: UUID
    actor_kind: str
    actor_key: str


@router.post("/sources", response_model=SourceResponse, status_code=201)
async def register_source(payload: SourceRegistration, service: Service):
    return await service.register_source(payload)


@router.get("/sources", response_model=list[SourceResponse])
async def sources(service: Service, limit: Limit = 100, offset: Offset = 0):
    return await service.list_records(AnalyticsProvider, limit=limit, offset=offset)


@router.post("/datasets", response_model=DatasetResponse, status_code=201)
async def create_dataset(payload: DatasetCreate, service: Service):
    return await service.create_dataset(payload)


@router.get("/datasets", response_model=list[DatasetResponse])
async def datasets(
    service: Service,
    provider_id: UUID | None = None,
    owner_department: str | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
):
    return await service.list_records(
        Dataset,
        provider_id=provider_id,
        owner_department=owner_department,
        limit=limit,
        offset=offset,
    )


@router.get("/datasets/{dataset_id}", response_model=DatasetResponse)
async def dataset(dataset_id: UUID, service: Service):
    return await service.get_record(Dataset, dataset_id)


@router.post(
    "/datasets/{dataset_id}/versions", response_model=VersionResponse, status_code=201
)
async def create_version(dataset_id: UUID, payload: VersionCreate, service: Service):
    return await service.create_version(dataset_id, payload)


@router.get("/datasets/{dataset_id}/versions", response_model=list[VersionResponse])
async def versions(
    dataset_id: UUID,
    service: Service,
    limit: Limit = 100,
    offset: Offset = 0,
    state: VersionState | None = None,
):
    await service.get_record(Dataset, dataset_id)
    return await service.list_records(
        DatasetVersion, dataset_id=dataset_id, state=state, limit=limit, offset=offset
    )


@router.get("/versions/{version_id}", response_model=VersionResponse)
async def version(version_id: UUID, service: Service):
    return await service.get_record(DatasetVersion, version_id)


@router.post("/versions/{version_id}/transitions", response_model=VersionResponse)
async def transition_version(
    version_id: UUID, payload: VersionTransition, service: Service
):
    return await service.transition_version(version_id, payload)


@router.post(
    "/versions/{version_id}/documentation",
    response_model=DocumentationResponse,
    status_code=201,
)
async def document(version_id: UUID, payload: DocumentationCreate, service: Service):
    return await service.document_version(version_id, payload)


@router.get(
    "/versions/{version_id}/documentation", response_model=list[DocumentationResponse]
)
async def documentation(
    version_id: UUID,
    service: Service,
    limit: Limit = 100,
    offset: Offset = 0,
    state: DocumentationState | None = None,
):
    await service.get_record(DatasetVersion, version_id)
    return await service.list_records(
        DatasetDocumentation,
        version_id=version_id,
        state=state,
        limit=limit,
        offset=offset,
    )


@router.get("/documentation/{documentation_id}", response_model=DocumentationResponse)
async def documentation_revision(documentation_id: UUID, service: Service):
    return await service.get_record(DatasetDocumentation, documentation_id)


@router.post(
    "/versions/{version_id}/documentation/transitions",
    response_model=DocumentationResponse,
    status_code=201,
)
async def transition_documentation(
    version_id: UUID, payload: DocumentationTransition, service: Service
):
    return await service.transition_documentation(version_id, payload)


@router.get("/versions/{version_id}/eligibility", response_model=Eligibility)
async def eligibility(version_id: UUID, service: Service):
    return await service.eligibility(version_id)


@router.post("/collection-runs", response_model=RunResponse, status_code=201)
async def create_run(payload: CollectionRunCreate, service: Service):
    return await service.create_run(payload)


@router.get("/collection-runs", response_model=list[RunResponse])
async def runs(
    service: Service,
    documentation_id: UUID | None = None,
    source_id: UUID | None = None,
    version_id: UUID | None = None,
    job_id: UUID | None = None,
    retry_of_id: UUID | None = None,
    status: RunStatus | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
):
    return await service.list_records(
        CollectionRun,
        documentation_id=documentation_id,
        source_id=source_id,
        version_id=version_id,
        job_id=job_id,
        retry_of_id=retry_of_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/collection-runs/{run_id}", response_model=RunResponse)
async def run(run_id: UUID, service: Service):
    return await service.get_record(CollectionRun, run_id)


@router.post("/collection-runs/{run_id}/transitions", response_model=RunResponse)
async def transition(run_id: UUID, payload: CollectionRunTransition, service: Service):
    return await service.transition_run(run_id, payload)


@router.post("/collection-runs/{run_id}/checkpoints", response_model=RunResponse)
async def checkpoint(run_id: UUID, payload: CollectionRunProgress, service: Service):
    return await service.checkpoint_run(run_id, payload)


@router.post("/transformations", response_model=TransformationResponse, status_code=201)
async def create_transformation(payload: TransformationCreate, service: Service):
    return await service.record_transformation(payload)


@router.get("/transformations", response_model=list[TransformationResponse])
async def transformations(
    service: Service,
    output_version_id: UUID | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
):
    return await service.list_records(
        DatasetTransformation,
        output_version_id=output_version_id,
        limit=limit,
        offset=offset,
    )


@router.get("/lineage", response_model=list[LineageResponse])
async def lineage(
    service: Service,
    transformation_id: UUID | None = None,
    input_version_id: UUID | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
):
    return await service.list_records(
        DatasetLineage,
        transformation_id=transformation_id,
        input_version_id=input_version_id,
        limit=limit,
        offset=offset,
    )


@router.get("/activity", response_model=list[ActivityResponse])
async def activity(
    service: Service,
    entity_id: UUID | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
):
    return await service.list_records(
        GovernanceActivity, entity_id=entity_id, limit=limit, offset=offset
    )
