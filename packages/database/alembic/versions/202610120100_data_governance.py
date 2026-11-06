"""Cross-department dataset governance; metadata only.

Revision ID: 202610120100
Revises: 202609210100
"""

from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision = "202610120100"
down_revision = "202609210100"
branch_labels = None
depends_on = None

capabilities = sa.table(
    "capabilities",
    sa.column("id", sa.Uuid()),
    sa.column("key", sa.String()),
    sa.column("display_name", sa.String()),
    sa.column("description", sa.String()),
    sa.column("system_capability", sa.Boolean()),
)
roles = sa.table(
    "roles",
    sa.column("id", sa.Uuid()),
    sa.column("key", sa.String()),
    sa.column("workspace_id", sa.Uuid()),
    sa.column("is_system_role", sa.Boolean()),
)
links = sa.table(
    "role_capabilities",
    sa.column("id", sa.Uuid()),
    sa.column("role_id", sa.Uuid()),
    sa.column("capability_id", sa.Uuid()),
    sa.column("source", sa.String()),
)


def seed_capability(KEY, role_keys):
    bind = op.get_bind()
    identifier = bind.scalar(
        sa.select(capabilities.c.id).where(capabilities.c.key == KEY)
    )
    if identifier is None:
        identifier = uuid5(NAMESPACE_URL, f"labelos-capability:{KEY}")
        bind.execute(
            capabilities.insert().values(
                id=identifier,
                key=KEY,
                display_name=KEY,
                description="Cross-department dataset governance.",
                system_capability=True,
            )
        )
    for role_id, role_key in bind.execute(
        sa.select(roles.c.id, roles.c.key).where(
            roles.c.workspace_id.is_(None),
            roles.c.is_system_role.is_(True),
            roles.c.key.in_(role_keys),
        )
    ):
        existing = bind.scalar(
            sa.select(links.c.id).where(
                links.c.role_id == role_id,
                links.c.capability_id == identifier,
            )
        )
        if existing is None:
            bind.execute(
                links.insert().values(
                    id=uuid5(
                        NAMESPACE_URL, f"labelos-role-capability:{role_key}:{KEY}"
                    ),
                    role_id=role_id,
                    capability_id=identifier,
                    source="system_default",
                )
            )


# Frozen guards: historical migrations must not import evolving model code.
def guard_statements(dialect):
    immutable = (
        "datasets",
        "dataset_versions",
        "dataset_documentation",
        "dataset_transformations",
        "dataset_lineage",
        "governance_activity",
    )
    checks = {table: {"UPDATE": "1 = 1", "DELETE": "1 = 1"} for table in immutable}
    distinct = "IS DISTINCT FROM" if dialect == "postgresql" else "IS NOT"
    fixed = (
        "id",
        "organization_id",
        "documentation_id",
        "run_key",
        "production",
        "created_at",
    )
    changed = " OR ".join(f"OLD.{c} {distinct} NEW.{c}" for c in fixed)
    checks["collection_runs"] = {
        "INSERT": "NEW.status != 'queued'",
        "UPDATE": f"({changed}) OR NOT ((OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled')) OR (OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed', 'cancelled'))) OR (OLD.started_at IS NOT NULL AND OLD.started_at {distinct} NEW.started_at)",
        "DELETE": "1 = 1",
    }
    # Ordering versions makes the lineage graph acyclic, including direct SQL writes.
    checks["dataset_lineage"][
        "INSERT"
    ] = "NOT EXISTS (SELECT 1 FROM dataset_transformations t JOIN dataset_versions o ON o.id = t.output_version_id JOIN dataset_versions i ON i.id = NEW.input_version_id WHERE t.id = NEW.transformation_id AND i.created_at < o.created_at)"
    statements = []
    for table, operations in checks.items():
        for operation, condition in operations.items():
            name = f"{table}_{operation.lower()}_governance_guard"
            if dialect == "postgresql":
                statements.extend(
                    [
                        f"CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {condition} THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
                        f"CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}()",
                    ]
                )
            else:
                statements.append(
                    f"CREATE TRIGGER {name} BEFORE {operation} ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END"
                )
    return statements


def upgrade() -> None:
    op.create_index(
        "uq_analytics_providers_id_organization",
        "analytics_providers",
        ["id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "datasets",
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("owner_department", sa.String(length=80), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_datasets_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id", "organization_id"],
            ["analytics_providers.id", "analytics_providers.organization_id"],
            name=op.f("fk_datasets_provider_id_analytics_providers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_datasets")),
        sa.UniqueConstraint("id", "organization_id", name=op.f("uq_datasets_id")),
        sa.UniqueConstraint(
            "organization_id", "key", name=op.f("uq_datasets_organization_id")
        ),
    )
    op.create_index(
        "ix_datasets_organization_id", "datasets", ["organization_id"], unique=False
    )
    op.create_table(
        "dataset_versions",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("version_key", sa.String(length=120), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "organization_id"],
            ["datasets.id", "datasets.organization_id"],
            name=op.f("fk_dataset_versions_dataset_id_datasets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_dataset_versions_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_versions")),
        sa.UniqueConstraint(
            "dataset_id", "version_key", name=op.f("uq_dataset_versions_dataset_id")
        ),
        sa.UniqueConstraint(
            "id", "organization_id", name=op.f("uq_dataset_versions_id")
        ),
    )
    op.create_table(
        "dataset_documentation",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("production_eligible", sa.Boolean(), nullable=False),
        sa.Column("change_reason", sa.String(length=1000), nullable=False),
        sa.Column("actor_kind", sa.String(length=40), nullable=False),
        sa.Column("actor_key", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision > 0", name=op.f("ck_dataset_documentation_positive_revision")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_dataset_documentation_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "organization_id"],
            ["dataset_versions.id", "dataset_versions.organization_id"],
            name=op.f("fk_dataset_documentation_version_id_dataset_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_documentation")),
        sa.UniqueConstraint(
            "id", "organization_id", name=op.f("uq_dataset_documentation_id")
        ),
        sa.UniqueConstraint(
            "version_id", "revision", name=op.f("uq_dataset_documentation_version_id")
        ),
    )
    op.create_table(
        "collection_runs",
        sa.Column("documentation_id", sa.Uuid(), nullable=False),
        sa.Column("run_key", sa.String(length=160), nullable=False),
        sa.Column("production", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_written", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_rejected", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'failed' AND error_code IS NOT NULL) OR (status != 'failed' AND error_code IS NULL)",
            name=op.f("ck_collection_runs_failure_error"),
        ),
        sa.CheckConstraint(
            "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL) OR (status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL) OR (status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL)",
            name=op.f("ck_collection_runs_status_timestamps"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_collection_runs_status"),
        ),
        sa.CheckConstraint(
            "(started_at IS NULL OR started_at >= created_at) AND (completed_at IS NULL OR completed_at >= created_at) AND (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)",
            name=op.f("ck_collection_runs_timestamp_order"),
        ),
        sa.CheckConstraint(
            "records_seen >= 0 AND records_written >= 0 AND records_rejected >= 0 AND records_written + records_rejected <= records_seen",
            name=op.f("ck_collection_runs_counts"),
        ),
        sa.ForeignKeyConstraint(
            ["documentation_id", "organization_id"],
            ["dataset_documentation.id", "dataset_documentation.organization_id"],
            name=op.f("fk_collection_runs_documentation_id_dataset_documentation"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_collection_runs_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_runs")),
        sa.UniqueConstraint(
            "id", "organization_id", name=op.f("uq_collection_runs_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "run_key",
            name=op.f("uq_collection_runs_organization_id"),
        ),
    )
    op.create_index(
        "ix_collection_runs_organization_id",
        "collection_runs",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "dataset_transformations",
        sa.Column("output_version_id", sa.Uuid(), nullable=False),
        sa.Column("collection_run_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("code_reference", sa.String(length=255), nullable=False),
        sa.Column("parameters_sha256", sa.String(length=64), nullable=True),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["collection_run_id", "organization_id"],
            ["collection_runs.id", "collection_runs.organization_id"],
            name=op.f("fk_dataset_transformations_collection_run_id_collection_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_dataset_transformations_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["output_version_id", "organization_id"],
            ["dataset_versions.id", "dataset_versions.organization_id"],
            name=op.f("fk_dataset_transformations_output_version_id_dataset_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_transformations")),
        sa.UniqueConstraint(
            "id", "organization_id", name=op.f("uq_dataset_transformations_id")
        ),
        sa.UniqueConstraint(
            "output_version_id",
            name=op.f("uq_dataset_transformations_output_version_id"),
        ),
    )
    op.create_table(
        "dataset_lineage",
        sa.Column("transformation_id", sa.Uuid(), nullable=False),
        sa.Column("input_version_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["input_version_id", "organization_id"],
            ["dataset_versions.id", "dataset_versions.organization_id"],
            name=op.f("fk_dataset_lineage_input_version_id_dataset_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_dataset_lineage_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transformation_id", "organization_id"],
            ["dataset_transformations.id", "dataset_transformations.organization_id"],
            name=op.f("fk_dataset_lineage_transformation_id_dataset_transformations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_lineage")),
        sa.UniqueConstraint(
            "transformation_id",
            "input_version_id",
            name=op.f("uq_dataset_lineage_transformation_id"),
        ),
    )
    op.create_index(
        "ix_dataset_lineage_input_version_id",
        "dataset_lineage",
        ["input_version_id"],
        unique=False,
    )
    op.create_table(
        "governance_activity",
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("actor_kind", sa.String(length=40), nullable=False),
        sa.Column("actor_key", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_governance_activity_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_governance_activity")),
    )
    op.create_index(
        "ix_governance_activity_organization_id",
        "governance_activity",
        ["organization_id"],
        unique=False,
    )

    for statement in guard_statements(op.get_bind().dialect.name):
        op.execute(statement)
    seed_capability(
        "governance.view",
        (
            "owner",
            "admin",
            "member",
            "a_and_r",
            "manager",
            "marketing",
            "legal",
            "finance",
        ),
    )
    seed_capability("governance.manage", ("owner", "admin"))


def downgrade() -> None:
    bind = op.get_bind()
    # Downgrades are administrative operations, but must not silently erase
    # immutable evidence or revoke grants before discovering retained history.
    if any(
        bind.scalar(sa.text(f"SELECT 1 FROM {table} LIMIT 1"))
        for table in (
            "governance_activity",
            "dataset_lineage",
            "dataset_transformations",
            "collection_runs",
            "dataset_documentation",
            "dataset_versions",
            "datasets",
        )
    ):
        raise RuntimeError("Governance history prevents downgrade")
    identifiers = sa.select(capabilities.c.id).where(
        capabilities.c.key.in_(("governance.view", "governance.manage"))
    )
    bind.execute(links.delete().where(links.c.capability_id.in_(identifiers)))
    bind.execute(
        capabilities.delete().where(
            capabilities.c.key.in_(("governance.view", "governance.manage"))
        )
    )
    op.drop_table("governance_activity")
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP FUNCTION IF EXISTS governance_activity_insert_governance_guard()"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS governance_activity_update_governance_guard()"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS governance_activity_delete_governance_guard()"
        )
    op.drop_table("dataset_lineage")
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS dataset_lineage_insert_governance_guard()")
        op.execute("DROP FUNCTION IF EXISTS dataset_lineage_update_governance_guard()")
        op.execute("DROP FUNCTION IF EXISTS dataset_lineage_delete_governance_guard()")
    op.drop_table("dataset_transformations")
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP FUNCTION IF EXISTS dataset_transformations_insert_governance_guard()"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS dataset_transformations_update_governance_guard()"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS dataset_transformations_delete_governance_guard()"
        )
    op.drop_table("collection_runs")
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS collection_runs_insert_governance_guard()")
        op.execute("DROP FUNCTION IF EXISTS collection_runs_update_governance_guard()")
        op.execute("DROP FUNCTION IF EXISTS collection_runs_delete_governance_guard()")
    op.drop_table("dataset_documentation")
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP FUNCTION IF EXISTS dataset_documentation_insert_governance_guard()"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS dataset_documentation_update_governance_guard()"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS dataset_documentation_delete_governance_guard()"
        )
    op.drop_table("dataset_versions")
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS dataset_versions_insert_governance_guard()")
        op.execute("DROP FUNCTION IF EXISTS dataset_versions_update_governance_guard()")
        op.execute("DROP FUNCTION IF EXISTS dataset_versions_delete_governance_guard()")
    op.drop_table("datasets")
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS datasets_insert_governance_guard()")
        op.execute("DROP FUNCTION IF EXISTS datasets_update_governance_guard()")
        op.execute("DROP FUNCTION IF EXISTS datasets_delete_governance_guard()")
    op.drop_index(
        "uq_analytics_providers_id_organization", table_name="analytics_providers"
    )
