"""Support governance ownership, provenance and audit-history lookups.

Revision ID: 202610130100
Revises: 202610120500
"""

from alembic import op

revision = "202610130100"
down_revision = "202610120500"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_datasets_provider_id", "datasets", ["provider_id"]),
    (
        "ix_dataset_versions_workspace_history",
        "dataset_versions",
        ["organization_id", "created_at", "id"],
    ),
    ("ix_collection_runs_documentation_id", "collection_runs", ["documentation_id"]),
    (
        "ix_dataset_transformations_collection_run_id",
        "dataset_transformations",
        ["collection_run_id"],
    ),
    (
        "ix_governance_activity_entity_history",
        "governance_activity",
        ["organization_id", "entity_id", "created_at", "id"],
    ),
    (
        "ix_provenance_transformations_collection_run_id",
        "provenance_transformations",
        ["collection_run_id"],
    ),
    ("ix_provenance_records_version_id", "provenance_records", ["version_id"]),
    (
        "ix_provenance_records_collection_run_id",
        "provenance_records",
        ["collection_run_id"],
    ),
    (
        "ix_provenance_records_workspace_history",
        "provenance_records",
        ["organization_id", "created_at", "id"],
    ),
)


def upgrade():
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade():
    # Only indexes are removed; all history and lifecycle guards remain intact.
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
