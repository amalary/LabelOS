"""Append-only record transformation lineage.

Revision ID: 202610120500
Revises: 202610120400
"""

import sqlalchemy as sa
from alembic import op

revision = "202610120500"
down_revision = "202610120400"
branch_labels = None
depends_on = None


def base_columns():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def scoped_fk(column, table):
    return sa.ForeignKeyConstraint(
        [column, "organization_id"],
        [f"{table}.id", f"{table}.organization_id"],
        ondelete="RESTRICT",
    )


def upgrade():
    op.create_table(
        "provenance_transformations",
        *base_columns(),
        sa.Column("transformation_type", sa.String(30), nullable=False),
        sa.Column("transformation_version", sa.String(160), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("collection_run_id", sa.Uuid()),
        sa.Column("actor_kind", sa.String(40), nullable=False),
        sa.Column("actor_key", sa.String(255), nullable=False),
        sa.UniqueConstraint(
            "id", "organization_id", name="uq_provenance_transformations_id"
        ),
        scoped_fk("version_id", "dataset_versions"),
        scoped_fk("collection_run_id", "collection_runs"),
        sa.CheckConstraint(
            "transformation_type IN ('normalize', 'transform', 'derive', 'merge')",
            name="type",
        ),
        sa.CheckConstraint("length(trim(transformation_version)) > 0", name="version"),
    )
    op.create_index(
        "ix_provenance_transformations_version_id",
        "provenance_transformations",
        ["version_id"],
    )
    op.create_table(
        "provenance_records",
        *base_columns(),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("collection_run_id", sa.Uuid()),
        sa.Column("transformation_id", sa.Uuid()),
        sa.Column("source_reference", sa.Uuid()),
        sa.Column("content_sha256", sa.String(64)),
        sa.Column("artist_id", sa.Uuid()),
        sa.Column("observation_id", sa.Uuid()),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.UniqueConstraint("id", "organization_id", name="uq_provenance_records_id"),
        scoped_fk("version_id", "dataset_versions"),
        scoped_fk("collection_run_id", "collection_runs"),
        scoped_fk("transformation_id", "provenance_transformations"),
        sa.CheckConstraint(
            "kind IN ('raw_source', 'normalized_artist', 'observation', 'derived_output')",
            name="kind",
        ),
        sa.CheckConstraint(
            "(kind = 'raw_source' AND generation = 0 AND transformation_id IS NULL AND collection_run_id IS NOT NULL AND source_reference IS NOT NULL) OR (kind != 'raw_source' AND generation > 0 AND transformation_id IS NOT NULL AND source_reference IS NULL)",
            name="origin",
        ),
        sa.CheckConstraint(
            "(kind = 'normalized_artist' AND artist_id IS NOT NULL AND observation_id IS NULL) OR (kind = 'observation' AND artist_id IS NULL) OR (kind IN ('raw_source', 'derived_output') AND artist_id IS NULL AND observation_id IS NULL)",
            name="binding",
        ),
    )
    for name, columns in (
        ("artist_id", ["organization_id", "artist_id"]),
        ("observation_id", ["organization_id", "observation_id"]),
        ("transformation_id", ["transformation_id"]),
    ):
        op.create_index(f"ix_provenance_records_{name}", "provenance_records", columns)
    op.create_table(
        "provenance_edges",
        *base_columns(),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("output_id", sa.Uuid(), nullable=False),
        sa.UniqueConstraint(
            "input_id", "output_id", name="uq_provenance_edges_input_id"
        ),
        scoped_fk("input_id", "provenance_records"),
        scoped_fk("output_id", "provenance_records"),
        sa.CheckConstraint("input_id != output_id", name="distinct"),
    )
    op.create_index("ix_provenance_edges_output_id", "provenance_edges", ["output_id"])
    for statement in GUARDS[op.get_bind().dialect.name]:
        op.execute(statement)


def downgrade():
    bind = op.get_bind()
    tables = ("provenance_edges", "provenance_records", "provenance_transformations")
    if any(bind.scalar(sa.text(f"SELECT count(*) FROM {table}")) for table in tables):
        raise RuntimeError("Cannot discard recorded transformation lineage")
    for table in tables:
        op.drop_table(table)
        if bind.dialect.name == "postgresql":
            for operation in ("insert", "update", "delete"):
                op.execute(
                    f"DROP FUNCTION IF EXISTS {table}_{operation}_provenance_guard()"
                )


# Frozen below; historical migrations must not depend on live application guards.
GUARDS = {
    "sqlite": [
        "CREATE TRIGGER provenance_transformations_insert_provenance_guard BEFORE INSERT ON provenance_transformations WHEN (NEW.collection_run_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM collection_runs r WHERE r.id = NEW.collection_run_id AND r.organization_id = NEW.organization_id AND r.status IN ('running', 'completed', 'succeeded', 'partially_completed'))) OR NOT EXISTS (SELECT v.id FROM dataset_versions v WHERE v.id = NEW.version_id AND v.organization_id = NEW.organization_id AND v.state = 'draft') BEGIN SELECT RAISE(ABORT, 'Invalid or immutable provenance'); END",
        "CREATE TRIGGER provenance_transformations_update_provenance_guard BEFORE UPDATE ON provenance_transformations WHEN 1 = 1 BEGIN SELECT RAISE(ABORT, 'Invalid or immutable provenance'); END",
        "CREATE TRIGGER provenance_transformations_delete_provenance_guard BEFORE DELETE ON provenance_transformations WHEN 1 = 1 BEGIN SELECT RAISE(ABORT, 'Invalid or immutable provenance'); END",
        "CREATE TRIGGER provenance_records_insert_provenance_guard BEFORE INSERT ON provenance_records WHEN ((NEW.collection_run_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM collection_runs r JOIN dataset_documentation d ON d.id = r.documentation_id WHERE r.id = NEW.collection_run_id AND r.organization_id = NEW.organization_id AND d.version_id = NEW.version_id AND r.status IN ('running', 'completed', 'succeeded', 'partially_completed'))) OR (NEW.transformation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM provenance_transformations t WHERE t.id = NEW.transformation_id AND t.organization_id = NEW.organization_id AND t.version_id = NEW.version_id AND ((NEW.kind = 'normalized_artist' AND t.transformation_type IN ('normalize', 'merge')) OR (NEW.kind = 'observation' AND t.transformation_type = 'transform') OR (NEW.kind = 'derived_output' AND t.transformation_type = 'derive')))) OR (NEW.artist_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artists a WHERE a.id = NEW.artist_id AND a.organization_id = NEW.organization_id)) OR (NEW.observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM analytics_observations a WHERE a.id = NEW.observation_id AND a.organization_id = NEW.organization_id))) OR NOT EXISTS (SELECT v.id FROM dataset_versions v WHERE v.id = NEW.version_id AND v.organization_id = NEW.organization_id AND v.state = 'draft') BEGIN SELECT RAISE(ABORT, 'Invalid or immutable provenance'); END",
        "CREATE TRIGGER provenance_records_update_provenance_guard BEFORE UPDATE ON provenance_records WHEN 1 = 1 BEGIN SELECT RAISE(ABORT, 'Invalid or immutable provenance'); END",
        "CREATE TRIGGER provenance_records_delete_provenance_guard BEFORE DELETE ON provenance_records WHEN 1 = 1 BEGIN SELECT RAISE(ABORT, 'Invalid or immutable provenance'); END",
        "CREATE TRIGGER provenance_edges_insert_provenance_guard BEFORE INSERT ON provenance_edges WHEN (NOT EXISTS (SELECT 1 FROM provenance_records i JOIN provenance_records o ON o.id = NEW.output_id WHERE i.id = NEW.input_id AND i.organization_id = NEW.organization_id AND o.organization_id = NEW.organization_id AND i.generation < o.generation)) OR NOT EXISTS (SELECT v.id FROM dataset_versions v JOIN provenance_records r ON r.version_id = v.id WHERE r.id = NEW.output_id AND v.organization_id = NEW.organization_id AND v.state = 'draft') BEGIN SELECT RAISE(ABORT, 'Invalid or immutable provenance'); END",
        "CREATE TRIGGER provenance_edges_update_provenance_guard BEFORE UPDATE ON provenance_edges WHEN 1 = 1 BEGIN SELECT RAISE(ABORT, 'Invalid or immutable provenance'); END",
        "CREATE TRIGGER provenance_edges_delete_provenance_guard BEFORE DELETE ON provenance_edges WHEN 1 = 1 BEGIN SELECT RAISE(ABORT, 'Invalid or immutable provenance'); END",
    ],
    "postgresql": [
        "CREATE FUNCTION provenance_transformations_insert_provenance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM v.id FROM dataset_versions v WHERE v.id = NEW.version_id FOR UPDATE OF v; IF (NEW.collection_run_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM collection_runs r WHERE r.id = NEW.collection_run_id AND r.organization_id = NEW.organization_id AND r.status IN ('running', 'completed', 'succeeded', 'partially_completed'))) OR NOT EXISTS (SELECT v.id FROM dataset_versions v WHERE v.id = NEW.version_id AND v.organization_id = NEW.organization_id AND v.state = 'draft') THEN RAISE EXCEPTION 'Invalid or immutable provenance'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER provenance_transformations_insert_provenance_guard BEFORE INSERT ON provenance_transformations FOR EACH ROW EXECUTE FUNCTION provenance_transformations_insert_provenance_guard()",
        "CREATE FUNCTION provenance_transformations_update_provenance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF 1 = 1 THEN RAISE EXCEPTION 'Invalid or immutable provenance'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER provenance_transformations_update_provenance_guard BEFORE UPDATE ON provenance_transformations FOR EACH ROW EXECUTE FUNCTION provenance_transformations_update_provenance_guard()",
        "CREATE FUNCTION provenance_transformations_delete_provenance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF 1 = 1 THEN RAISE EXCEPTION 'Invalid or immutable provenance'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER provenance_transformations_delete_provenance_guard BEFORE DELETE ON provenance_transformations FOR EACH ROW EXECUTE FUNCTION provenance_transformations_delete_provenance_guard()",
        "CREATE FUNCTION provenance_records_insert_provenance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM v.id FROM dataset_versions v WHERE v.id = NEW.version_id FOR UPDATE OF v; IF ((NEW.collection_run_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM collection_runs r JOIN dataset_documentation d ON d.id = r.documentation_id WHERE r.id = NEW.collection_run_id AND r.organization_id = NEW.organization_id AND d.version_id = NEW.version_id AND r.status IN ('running', 'completed', 'succeeded', 'partially_completed'))) OR (NEW.transformation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM provenance_transformations t WHERE t.id = NEW.transformation_id AND t.organization_id = NEW.organization_id AND t.version_id = NEW.version_id AND ((NEW.kind = 'normalized_artist' AND t.transformation_type IN ('normalize', 'merge')) OR (NEW.kind = 'observation' AND t.transformation_type = 'transform') OR (NEW.kind = 'derived_output' AND t.transformation_type = 'derive')))) OR (NEW.artist_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artists a WHERE a.id = NEW.artist_id AND a.organization_id = NEW.organization_id)) OR (NEW.observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM analytics_observations a WHERE a.id = NEW.observation_id AND a.organization_id = NEW.organization_id))) OR NOT EXISTS (SELECT v.id FROM dataset_versions v WHERE v.id = NEW.version_id AND v.organization_id = NEW.organization_id AND v.state = 'draft') THEN RAISE EXCEPTION 'Invalid or immutable provenance'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER provenance_records_insert_provenance_guard BEFORE INSERT ON provenance_records FOR EACH ROW EXECUTE FUNCTION provenance_records_insert_provenance_guard()",
        "CREATE FUNCTION provenance_records_update_provenance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF 1 = 1 THEN RAISE EXCEPTION 'Invalid or immutable provenance'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER provenance_records_update_provenance_guard BEFORE UPDATE ON provenance_records FOR EACH ROW EXECUTE FUNCTION provenance_records_update_provenance_guard()",
        "CREATE FUNCTION provenance_records_delete_provenance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF 1 = 1 THEN RAISE EXCEPTION 'Invalid or immutable provenance'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER provenance_records_delete_provenance_guard BEFORE DELETE ON provenance_records FOR EACH ROW EXECUTE FUNCTION provenance_records_delete_provenance_guard()",
        "CREATE FUNCTION provenance_edges_insert_provenance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM v.id FROM dataset_versions v JOIN provenance_records r ON r.version_id = v.id WHERE r.id = NEW.output_id FOR UPDATE OF v; IF (NOT EXISTS (SELECT 1 FROM provenance_records i JOIN provenance_records o ON o.id = NEW.output_id WHERE i.id = NEW.input_id AND i.organization_id = NEW.organization_id AND o.organization_id = NEW.organization_id AND i.generation < o.generation)) OR NOT EXISTS (SELECT v.id FROM dataset_versions v JOIN provenance_records r ON r.version_id = v.id WHERE r.id = NEW.output_id AND v.organization_id = NEW.organization_id AND v.state = 'draft') THEN RAISE EXCEPTION 'Invalid or immutable provenance'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER provenance_edges_insert_provenance_guard BEFORE INSERT ON provenance_edges FOR EACH ROW EXECUTE FUNCTION provenance_edges_insert_provenance_guard()",
        "CREATE FUNCTION provenance_edges_update_provenance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF 1 = 1 THEN RAISE EXCEPTION 'Invalid or immutable provenance'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER provenance_edges_update_provenance_guard BEFORE UPDATE ON provenance_edges FOR EACH ROW EXECUTE FUNCTION provenance_edges_update_provenance_guard()",
        "CREATE FUNCTION provenance_edges_delete_provenance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF 1 = 1 THEN RAISE EXCEPTION 'Invalid or immutable provenance'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER provenance_edges_delete_provenance_guard BEFORE DELETE ON provenance_edges FOR EACH ROW EXECUTE FUNCTION provenance_edges_delete_provenance_guard()",
    ],
}
