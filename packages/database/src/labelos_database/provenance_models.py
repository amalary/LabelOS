"""Append-only record provenance, stored in the existing relational database."""

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from labelos_database.base import Base
from labelos_database.governance_models import GovernanceRecord
from labelos_database.provenance_guards import register_provenance_guards


def scoped_fk(column, table):
    return ForeignKeyConstraint(
        [column, "organization_id"],
        [f"{table}.id", f"{table}.organization_id"],
        ondelete="RESTRICT",
    )


class ProvenanceTransformation(Base, GovernanceRecord):
    __tablename__ = "provenance_transformations"
    transformation_type: Mapped[str] = mapped_column(String(30))
    transformation_version: Mapped[str] = mapped_column(String(160))
    version_id: Mapped[UUID]
    collection_run_id: Mapped[UUID | None]
    actor_kind: Mapped[str] = mapped_column(String(40))
    actor_key: Mapped[str] = mapped_column(String(255))
    __table_args__ = (
        UniqueConstraint("id", "organization_id"),
        scoped_fk("version_id", "dataset_versions"),
        scoped_fk("collection_run_id", "collection_runs"),
        CheckConstraint(
            "transformation_type IN ('normalize', 'transform', 'derive', 'merge')",
            name="type",
        ),
        CheckConstraint("length(trim(transformation_version)) > 0", name="version"),
        Index("ix_provenance_transformations_version_id", "version_id"),
        Index("ix_provenance_transformations_collection_run_id", "collection_run_id"),
    )


class ProvenanceRecord(Base, GovernanceRecord):
    __tablename__ = "provenance_records"
    kind: Mapped[str] = mapped_column(String(30))
    version_id: Mapped[UUID]
    collection_run_id: Mapped[UUID | None]
    transformation_id: Mapped[UUID | None]
    # An immutable snapshot reference; payloads remain in their authorized store.
    source_reference: Mapped[UUID | None]
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    artist_id: Mapped[UUID | None]
    observation_id: Mapped[UUID | None]
    generation: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("id", "organization_id"),
        scoped_fk("version_id", "dataset_versions"),
        scoped_fk("collection_run_id", "collection_runs"),
        scoped_fk("transformation_id", "provenance_transformations"),
        CheckConstraint(
            "kind IN ('raw_source', 'normalized_artist', 'observation', 'derived_output')",
            name="kind",
        ),
        CheckConstraint(
            "(kind = 'raw_source' AND generation = 0 AND transformation_id IS NULL AND collection_run_id IS NOT NULL AND source_reference IS NOT NULL) OR (kind != 'raw_source' AND generation > 0 AND transformation_id IS NOT NULL AND source_reference IS NULL)",
            name="origin",
        ),
        CheckConstraint(
            "(kind = 'normalized_artist' AND artist_id IS NOT NULL AND observation_id IS NULL) OR (kind = 'observation' AND artist_id IS NULL) OR (kind IN ('raw_source', 'derived_output') AND artist_id IS NULL AND observation_id IS NULL)",
            name="binding",
        ),
        Index("ix_provenance_records_artist_id", "organization_id", "artist_id"),
        Index(
            "ix_provenance_records_observation_id", "organization_id", "observation_id"
        ),
        Index("ix_provenance_records_transformation_id", "transformation_id"),
        Index("ix_provenance_records_version_id", "version_id"),
        Index("ix_provenance_records_collection_run_id", "collection_run_id"),
        Index(
            "ix_provenance_records_workspace_history",
            "organization_id",
            "created_at",
            "id",
        ),
    )


class ProvenanceEdge(Base, GovernanceRecord):
    __tablename__ = "provenance_edges"
    input_id: Mapped[UUID]
    output_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("input_id", "output_id"),
        scoped_fk("input_id", "provenance_records"),
        scoped_fk("output_id", "provenance_records"),
        CheckConstraint("input_id != output_id", name="distinct"),
        Index("ix_provenance_edges_output_id", "output_id"),
    )


register_provenance_guards(
    ProvenanceTransformation.__table__,
    ProvenanceRecord.__table__,
    ProvenanceEdge.__table__,
)
