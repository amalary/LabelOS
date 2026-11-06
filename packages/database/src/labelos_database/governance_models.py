"""Workspace-wide metadata and provenance. Never a raw payload store."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column

from labelos_database.base import Base, Timestamp, UUIDPrimaryKey
from labelos_database.governance_guards import register_governance_guards


class GovernanceRecord:
    id: Mapped[UUIDPrimaryKey]
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[Timestamp]


class Dataset(Base, GovernanceRecord):
    __tablename__ = "datasets"
    key: Mapped[str] = mapped_column(String(160))
    display_name: Mapped[str] = mapped_column(String(200))
    provider_id: Mapped[UUID]
    owner_department: Mapped[str] = mapped_column(String(80))
    __table_args__ = (
        UniqueConstraint("id", "organization_id"),
        UniqueConstraint("organization_id", "key"),
        ForeignKeyConstraint(
            ["provider_id", "organization_id"],
            ["analytics_providers.id", "analytics_providers.organization_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_datasets_organization_id", "organization_id"),
        Index("ix_datasets_provider_id", "provider_id"),
    )


class DatasetVersion(Base, GovernanceRecord):
    __tablename__ = "dataset_versions"
    dataset_id: Mapped[UUID]
    version_key: Mapped[str] = mapped_column(String(120))
    schema_version: Mapped[str | None] = mapped_column(String(120))
    data_fingerprint: Mapped[str | None] = mapped_column(String(64))
    collection_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collection_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_references: Mapped[list | None] = mapped_column(JSON(none_as_null=True))
    # The insert guard validates same-dataset ancestry, including workspace and
    # temporal ordering. All versions are protected from deletion.
    parent_version_id: Mapped[UUID | None]
    state: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft"
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("id", "organization_id"),
        UniqueConstraint("dataset_id", "version_key"),
        Index(
            "ix_dataset_versions_workspace_history",
            "organization_id",
            "created_at",
            "id",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "organization_id"],
            ["datasets.id", "datasets.organization_id"],
            ondelete="RESTRICT",
        ),
    )


class DatasetDocumentation(Base, GovernanceRecord):
    __tablename__ = "dataset_documentation"
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint("state IN ('draft', 'validated', 'published')", name="state"),
        default="draft",
        server_default="draft",
    )
    # NULL on pre-lifecycle records means this revision authored its own content.
    authored_revision: Mapped[int | None] = mapped_column(
        Integer,
        CheckConstraint(
            "authored_revision IS NULL OR "
            "(authored_revision > 0 AND authored_revision <= revision)",
            name="authored_revision",
        ),
    )
    document: Mapped[dict] = mapped_column(JSON)
    document_sha256: Mapped[str] = mapped_column(String(64))
    production_eligible: Mapped[bool] = mapped_column(Boolean)
    change_reason: Mapped[str] = mapped_column(String(1000))
    actor_kind: Mapped[str] = mapped_column(String(40))
    actor_key: Mapped[str] = mapped_column(String(255))
    __table_args__ = (
        UniqueConstraint("id", "organization_id"),
        UniqueConstraint("version_id", "revision"),
        CheckConstraint("revision > 0", name="positive_revision"),
        ForeignKeyConstraint(
            ["version_id", "organization_id"],
            ["dataset_versions.id", "dataset_versions.organization_id"],
            ondelete="RESTRICT",
        ),
    )


class CollectionRun(Base, GovernanceRecord):
    __tablename__ = "collection_runs"
    documentation_id: Mapped[UUID] = mapped_column()
    run_key: Mapped[str] = mapped_column(String(160))
    production: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_seen: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    records_written: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    records_rejected: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    error_code: Mapped[str | None] = mapped_column(String(60))
    job_id: Mapped[UUID | None]
    retry_of_id: Mapped[UUID | None]
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkpoint: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    progress_revision: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    # Resolve immutable provenance without duplicating source/version ownership.
    version_id = column_property(
        select(DatasetDocumentation.version_id)
        .where(DatasetDocumentation.id == documentation_id)
        .scalar_subquery()
    )
    source_id = column_property(
        select(Dataset.provider_id)
        .join(DatasetVersion, DatasetVersion.dataset_id == Dataset.id)
        .join(
            DatasetDocumentation, DatasetDocumentation.version_id == DatasetVersion.id
        )
        .where(DatasetDocumentation.id == documentation_id)
        .scalar_subquery()
    )
    __table_args__ = (
        UniqueConstraint("id", "organization_id"),
        UniqueConstraint("organization_id", "run_key"),
        UniqueConstraint("retry_of_id", name="uq_collection_runs_retry_of_id"),
        ForeignKeyConstraint(
            ["retry_of_id", "organization_id"],
            ["collection_runs.id", "collection_runs.organization_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "attempt >= 1 AND attempt <= max_attempts AND max_attempts <= 20 "
            "AND progress_revision >= 0",
            name="retry_metadata",
        ),
        ForeignKeyConstraint(
            ["documentation_id", "organization_id"],
            ["dataset_documentation.id", "dataset_documentation.organization_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'completed', "
            "'partially_completed', 'failed', 'cancelled')",
            name="status",
        ),
        CheckConstraint(
            "records_seen >= 0 AND records_written >= 0 AND records_rejected >= 0 "
            "AND records_written + records_rejected <= records_seen",
            name="counts",
        ),
        CheckConstraint(
            "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL) "
            "OR (status = 'running' AND started_at IS NOT NULL "
            "AND completed_at IS NULL) OR (status IN "
            "('succeeded', 'completed', 'partially_completed', 'failed', 'cancelled') "
            "AND completed_at IS NOT NULL)",
            name="status_timestamps",
        ),
        CheckConstraint(
            "(started_at IS NULL OR started_at >= created_at) "
            "AND (completed_at IS NULL OR completed_at >= created_at) "
            "AND (completed_at IS NULL OR started_at IS NULL "
            "OR completed_at >= started_at)",
            name="timestamp_order",
        ),
        CheckConstraint(
            "(status IN ('failed', 'partially_completed') AND error_code IS NOT NULL) "
            "OR (status NOT IN ('failed', 'partially_completed') AND error_code IS NULL)",
            name="failure_error",
        ),
        Index("ix_collection_runs_organization_id", "organization_id"),
        Index("ix_collection_runs_documentation_id", "documentation_id"),
    )


class DatasetTransformation(Base, GovernanceRecord):
    __tablename__ = "dataset_transformations"
    output_version_id: Mapped[UUID]
    collection_run_id: Mapped[UUID | None]
    name: Mapped[str] = mapped_column(String(160))
    code_reference: Mapped[str] = mapped_column(String(255))
    parameters_sha256: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(2000))
    __table_args__ = (
        UniqueConstraint("id", "organization_id"),
        UniqueConstraint("output_version_id"),
        Index("ix_dataset_transformations_collection_run_id", "collection_run_id"),
        ForeignKeyConstraint(
            ["output_version_id", "organization_id"],
            ["dataset_versions.id", "dataset_versions.organization_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["collection_run_id", "organization_id"],
            ["collection_runs.id", "collection_runs.organization_id"],
            ondelete="RESTRICT",
        ),
    )


class DatasetLineage(Base, GovernanceRecord):
    __tablename__ = "dataset_lineage"
    transformation_id: Mapped[UUID]
    input_version_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("transformation_id", "input_version_id"),
        ForeignKeyConstraint(
            ["transformation_id", "organization_id"],
            ["dataset_transformations.id", "dataset_transformations.organization_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["input_version_id", "organization_id"],
            ["dataset_versions.id", "dataset_versions.organization_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_dataset_lineage_input_version_id", "input_version_id"),
    )


class GovernanceActivity(Base, GovernanceRecord):
    """Durable audit facts, independent of outbox delivery/retention."""

    __tablename__ = "governance_activity"
    action: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[UUID]
    actor_kind: Mapped[str] = mapped_column(String(40))
    actor_key: Mapped[str] = mapped_column(String(255))
    __table_args__ = (
        Index("ix_governance_activity_organization_id", "organization_id"),
        Index(
            "ix_governance_activity_entity_history",
            "organization_id",
            "entity_id",
            "created_at",
            "id",
        ),
    )


register_governance_guards(
    Dataset.__table__,
    DatasetVersion.__table__,
    DatasetDocumentation.__table__,
    CollectionRun.__table__,
    DatasetTransformation.__table__,
    DatasetLineage.__table__,
    GovernanceActivity.__table__,
)
