"""Reproducible dataset version metadata and finalization.

Revision ID: 202610120300
Revises: 202610120200
"""

import sqlalchemy as sa
from alembic import op

revision = "202610120300"
down_revision = "202610120200"
branch_labels = None
depends_on = None

NEW_GUARDS = {
    "postgresql": [
        "CREATE FUNCTION dataset_versions_update_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF (OLD.id IS DISTINCT FROM NEW.id OR OLD.organization_id IS DISTINCT FROM NEW.organization_id OR OLD.dataset_id IS DISTINCT FROM NEW.dataset_id OR OLD.version_key IS DISTINCT FROM NEW.version_key OR OLD.created_at IS DISTINCT FROM NEW.created_at OR OLD.schema_version IS DISTINCT FROM NEW.schema_version OR OLD.data_fingerprint IS DISTINCT FROM NEW.data_fingerprint OR OLD.collection_start IS DISTINCT FROM NEW.collection_start OR OLD.collection_end IS DISTINCT FROM NEW.collection_end OR CAST(OLD.source_references AS TEXT) IS DISTINCT FROM CAST(NEW.source_references AS TEXT) OR OLD.parent_version_id IS DISTINCT FROM NEW.parent_version_id) OR NOT ((OLD.state = 'draft' AND NEW.state = 'finalized' AND NOT (NEW.schema_version IS NULL OR NEW.data_fingerprint IS NULL OR NEW.collection_start IS NULL OR NEW.collection_end IS NULL OR NEW.source_references IS NULL) AND NEW.finalized_at IS NOT NULL AND NEW.finalized_at >= NEW.created_at AND NEW.archived_at IS NULL) OR (OLD.state = 'finalized' AND NEW.state = 'archived' AND NOT (OLD.finalized_at IS DISTINCT FROM NEW.finalized_at) AND NEW.archived_at IS NOT NULL AND NEW.archived_at >= NEW.finalized_at)) THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER dataset_versions_update_governance_guard BEFORE UPDATE ON dataset_versions FOR EACH ROW EXECUTE FUNCTION dataset_versions_update_governance_guard()",
        "CREATE FUNCTION dataset_versions_insert_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.state != 'draft' OR NEW.finalized_at IS NOT NULL OR NEW.archived_at IS NOT NULL OR ((NEW.schema_version IS NOT NULL AND length(trim(NEW.schema_version)) = 0) OR (NEW.data_fingerprint IS NOT NULL AND (NEW.data_fingerprint !~ '^[a-f0-9]{64}$')) OR ((NEW.collection_start IS NULL) != (NEW.collection_end IS NULL)) OR NEW.collection_end < NEW.collection_start OR (NEW.source_references IS NOT NULL AND (json_typeof(NEW.source_references) != 'array' OR json_array_length(NEW.source_references) NOT BETWEEN 1 AND 100 OR EXISTS (SELECT 1 FROM json_array_elements(NEW.source_references) e WHERE json_typeof(e) != 'string' OR length(trim(e #>> '{}')) NOT BETWEEN 1 AND 2000) OR (SELECT count(DISTINCT e #>> '{}') FROM json_array_elements(NEW.source_references) e) != json_array_length(NEW.source_references)))) OR (NEW.parent_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dataset_versions p WHERE p.id = NEW.parent_version_id AND p.dataset_id = NEW.dataset_id AND p.organization_id = NEW.organization_id AND p.state IN ('finalized', 'archived') AND p.created_at < NEW.created_at)) THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER dataset_versions_insert_governance_guard BEFORE INSERT ON dataset_versions FOR EACH ROW EXECUTE FUNCTION dataset_versions_insert_governance_guard()",
        "CREATE FUNCTION dataset_documentation_insert_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM v.id FROM dataset_versions v WHERE v.id = NEW.version_id FOR UPDATE OF v; IF NOT EXISTS (SELECT v.state FROM dataset_versions v WHERE v.id = NEW.version_id AND v.organization_id = NEW.organization_id AND v.state = 'draft') THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER dataset_documentation_insert_governance_guard BEFORE INSERT ON dataset_documentation FOR EACH ROW EXECUTE FUNCTION dataset_documentation_insert_governance_guard()",
        "CREATE FUNCTION dataset_transformations_insert_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM v.id FROM dataset_versions v WHERE v.id = NEW.output_version_id FOR UPDATE OF v; IF NOT EXISTS (SELECT v.state FROM dataset_versions v WHERE v.id = NEW.output_version_id AND v.organization_id = NEW.organization_id AND v.state = 'draft') THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER dataset_transformations_insert_governance_guard BEFORE INSERT ON dataset_transformations FOR EACH ROW EXECUTE FUNCTION dataset_transformations_insert_governance_guard()",
        "CREATE FUNCTION dataset_lineage_insert_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM v.id FROM dataset_versions v JOIN dataset_transformations t ON t.output_version_id = v.id WHERE t.id = NEW.transformation_id FOR UPDATE OF v; IF NOT EXISTS (SELECT v.state FROM dataset_versions v JOIN dataset_transformations t ON t.output_version_id = v.id WHERE t.id = NEW.transformation_id AND v.organization_id = NEW.organization_id AND v.state = 'draft') OR NOT EXISTS (SELECT 1 FROM dataset_transformations t JOIN dataset_versions o ON o.id = t.output_version_id JOIN dataset_versions i ON i.id = NEW.input_version_id WHERE t.id = NEW.transformation_id AND i.created_at < o.created_at) THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER dataset_lineage_insert_governance_guard BEFORE INSERT ON dataset_lineage FOR EACH ROW EXECUTE FUNCTION dataset_lineage_insert_governance_guard()",
    ],
    "sqlite": [
        "CREATE TRIGGER dataset_versions_update_governance_guard BEFORE UPDATE ON dataset_versions WHEN (OLD.id IS NOT NEW.id OR OLD.organization_id IS NOT NEW.organization_id OR OLD.dataset_id IS NOT NEW.dataset_id OR OLD.version_key IS NOT NEW.version_key OR OLD.created_at IS NOT NEW.created_at OR OLD.schema_version IS NOT NEW.schema_version OR OLD.data_fingerprint IS NOT NEW.data_fingerprint OR OLD.collection_start IS NOT NEW.collection_start OR OLD.collection_end IS NOT NEW.collection_end OR CAST(OLD.source_references AS TEXT) IS NOT CAST(NEW.source_references AS TEXT) OR OLD.parent_version_id IS NOT NEW.parent_version_id) OR NOT ((OLD.state = 'draft' AND NEW.state = 'finalized' AND NOT (NEW.schema_version IS NULL OR NEW.data_fingerprint IS NULL OR NEW.collection_start IS NULL OR NEW.collection_end IS NULL OR NEW.source_references IS NULL) AND NEW.finalized_at IS NOT NULL AND NEW.finalized_at >= NEW.created_at AND NEW.archived_at IS NULL) OR (OLD.state = 'finalized' AND NEW.state = 'archived' AND NOT (OLD.finalized_at IS NOT NEW.finalized_at) AND NEW.archived_at IS NOT NULL AND NEW.archived_at >= NEW.finalized_at)) BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
        "CREATE TRIGGER dataset_versions_insert_governance_guard BEFORE INSERT ON dataset_versions WHEN NEW.state != 'draft' OR NEW.finalized_at IS NOT NULL OR NEW.archived_at IS NOT NULL OR ((NEW.schema_version IS NOT NULL AND length(trim(NEW.schema_version)) = 0) OR (NEW.data_fingerprint IS NOT NULL AND (length(NEW.data_fingerprint) != 64 OR NEW.data_fingerprint GLOB '*[^a-f0-9]*')) OR ((NEW.collection_start IS NULL) != (NEW.collection_end IS NULL)) OR NEW.collection_end < NEW.collection_start OR (NEW.source_references IS NOT NULL AND (json_type(NEW.source_references) != 'array' OR json_array_length(NEW.source_references) NOT BETWEEN 1 AND 100 OR EXISTS (SELECT 1 FROM json_each(NEW.source_references) e WHERE e.type != 'text' OR length(trim(e.value)) NOT BETWEEN 1 AND 2000) OR (SELECT count(DISTINCT e.value) FROM json_each(NEW.source_references) e) != json_array_length(NEW.source_references)))) OR (NEW.parent_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dataset_versions p WHERE p.id = NEW.parent_version_id AND p.dataset_id = NEW.dataset_id AND p.organization_id = NEW.organization_id AND p.state IN ('finalized', 'archived') AND p.created_at < NEW.created_at)) BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
        "CREATE TRIGGER dataset_documentation_insert_governance_guard BEFORE INSERT ON dataset_documentation WHEN NOT EXISTS (SELECT v.state FROM dataset_versions v WHERE v.id = NEW.version_id AND v.organization_id = NEW.organization_id AND v.state = 'draft') BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
        "CREATE TRIGGER dataset_transformations_insert_governance_guard BEFORE INSERT ON dataset_transformations WHEN NOT EXISTS (SELECT v.state FROM dataset_versions v WHERE v.id = NEW.output_version_id AND v.organization_id = NEW.organization_id AND v.state = 'draft') BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
        "CREATE TRIGGER dataset_lineage_insert_governance_guard BEFORE INSERT ON dataset_lineage WHEN NOT EXISTS (SELECT v.state FROM dataset_versions v JOIN dataset_transformations t ON t.output_version_id = v.id WHERE t.id = NEW.transformation_id AND v.organization_id = NEW.organization_id AND v.state = 'draft') OR NOT EXISTS (SELECT 1 FROM dataset_transformations t JOIN dataset_versions o ON o.id = t.output_version_id JOIN dataset_versions i ON i.id = NEW.input_version_id WHERE t.id = NEW.transformation_id AND i.created_at < o.created_at) BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
    ],
}

OLD_GUARDS = {
    "postgresql": [
        "CREATE FUNCTION dataset_versions_update_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF 1 = 1 THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER dataset_versions_update_governance_guard BEFORE UPDATE ON dataset_versions FOR EACH ROW EXECUTE FUNCTION dataset_versions_update_governance_guard()",
        "CREATE FUNCTION dataset_lineage_insert_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NOT EXISTS (SELECT 1 FROM dataset_transformations t JOIN dataset_versions o ON o.id = t.output_version_id JOIN dataset_versions i ON i.id = NEW.input_version_id WHERE t.id = NEW.transformation_id AND i.created_at < o.created_at) THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER dataset_lineage_insert_governance_guard BEFORE INSERT ON dataset_lineage FOR EACH ROW EXECUTE FUNCTION dataset_lineage_insert_governance_guard()",
    ],
    "sqlite": [
        "CREATE TRIGGER dataset_versions_update_governance_guard BEFORE UPDATE ON dataset_versions WHEN 1 = 1 BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
        "CREATE TRIGGER dataset_lineage_insert_governance_guard BEFORE INSERT ON dataset_lineage WHEN NOT EXISTS (SELECT 1 FROM dataset_transformations t JOIN dataset_versions o ON o.id = t.output_version_id JOIN dataset_versions i ON i.id = NEW.input_version_id WHERE t.id = NEW.transformation_id AND i.created_at < o.created_at) BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
    ],
}


def replace_guards(statements):
    dialect = op.get_bind().dialect.name
    for table, operation in (
        ("dataset_versions", "insert"),
        ("dataset_versions", "update"),
        ("dataset_documentation", "insert"),
        ("dataset_transformations", "insert"),
        ("dataset_lineage", "insert"),
    ):
        name = f"{table}_{operation}_governance_guard"
        suffix = f" ON {table}" if dialect == "postgresql" else ""
        op.execute(f"DROP TRIGGER IF EXISTS {name}{suffix}")
        if dialect == "postgresql":
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    for statement in statements[dialect]:
        op.execute(statement)


def upgrade():
    # Legacy identifiers/history remain intact. Unknown metadata stays NULL;
    # legacy versions remain drafts and are never falsely marked reproducible.
    for column in (
        sa.Column("schema_version", sa.String(120), nullable=True),
        sa.Column("data_fingerprint", sa.String(64), nullable=True),
        sa.Column("collection_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collection_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_references", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("parent_version_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("dataset_versions", column)
    replace_guards(NEW_GUARDS)


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT 1 FROM dataset_versions WHERE state != 'draft' "
            "OR schema_version IS NOT NULL OR data_fingerprint IS NOT NULL "
            "OR collection_start IS NOT NULL OR collection_end IS NOT NULL "
            "OR source_references IS NOT NULL OR parent_version_id IS NOT NULL "
            "OR finalized_at IS NOT NULL OR archived_at IS NOT NULL LIMIT 1"
        )
    ):
        raise RuntimeError("Dataset version history prevents downgrade")
    replace_guards(OLD_GUARDS)
    for column in (
        "archived_at",
        "finalized_at",
        "state",
        "parent_version_id",
        "source_references",
        "collection_end",
        "collection_start",
        "data_fingerprint",
        "schema_version",
    ):
        op.drop_column("dataset_versions", column)
