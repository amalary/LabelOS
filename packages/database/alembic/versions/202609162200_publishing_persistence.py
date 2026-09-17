"""Publishing persistence: immutable intent, starts and observations."""

import sqlalchemy as sa
from alembic import op

revision = "202609162200"
down_revision = "202609152100"
branch_labels = None
depends_on = None

# Frozen guard definitions; do not import application schema in revisions.
IMMUTABLE = (
    "id",
    "workspace_id",
    "scheduling_job_id",
    "marketing_content_item_id",
    "marketing_content_item_channel_id",
    "social_account_connection_id",
    "approval_request_id",
    "authorized_content_revision",
    "schedule_generation",
    "provider",
    "receipt_id",
    "idempotency_key",
    "payload_schema_version",
    "payload_fingerprint",
    "canonical_envelope",
    "correlation_id",
    "created_at",
)


def guard_statements(dialect):
    distinct = "IS DISTINCT FROM" if dialect == "postgresql" else "IS NOT"
    changed = " OR ".join(f"OLD.{c} {distinct} NEW.{c}" for c in IMMUTABLE)
    checks = {
        "publications": {
            "INSERT": "NEW.status != 'pending' OR NEW.transition_version != 0 OR NEW.updated_at != NEW.created_at",
            "UPDATE": f"({changed}) OR OLD.status IN ('published', 'permanent_failure', 'cancelled') OR NEW.transition_version != OLD.transition_version + 1 OR NEW.updated_at < OLD.updated_at OR NOT ((OLD.status = 'pending' AND NEW.status IN ('processing', 'cancelled')) OR (OLD.status = 'retryable_failure' AND NEW.status IN ('retrying', 'cancelled')) OR (OLD.status IN ('processing', 'retrying') AND NEW.status IN ('published', 'retryable_failure', 'permanent_failure', 'manual_action_required')) OR (OLD.status = 'manual_action_required' AND NEW.status IN ('published', 'retryable_failure', 'permanent_failure')))",
            "DELETE": "1 = 1",
        },
        "publication_attempts": {
            "UPDATE": "1 = 1",
            "DELETE": "1 = 1",
            "INSERT": "NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id AND p.workspace_id = NEW.workspace_id AND p.status IN ('pending', 'retryable_failure') AND NEW.started_at >= p.updated_at) OR NEW.number != (SELECT count(*) + 1 FROM publication_attempts a WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id) OR (NEW.number > 1 AND NOT EXISTS (SELECT 1 FROM publication_transitions t JOIN publication_attempts a ON a.id = t.attempt_id WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id AND a.number = NEW.number - 1 AND t.outcome = 'retryable_failure' AND t.version = (SELECT max(x.version) FROM publication_transitions x WHERE x.publication_id = NEW.publication_id AND x.workspace_id = NEW.workspace_id)))",
        },
        "publication_transitions": {
            "UPDATE": "1 = 1",
            "DELETE": "1 = 1",
            "INSERT": "NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id AND p.workspace_id = NEW.workspace_id AND p.transition_version = NEW.version AND p.status = NEW.to_status AND p.updated_at = NEW.occurred_at) OR NEW.version != (SELECT count(*) + 1 FROM publication_transitions t WHERE t.publication_id = NEW.publication_id AND t.workspace_id = NEW.workspace_id) OR (NEW.version = 1 AND NEW.from_status != 'pending') OR (NEW.version > 1 AND NOT EXISTS (SELECT 1 FROM publication_transitions t WHERE t.publication_id = NEW.publication_id AND t.workspace_id = NEW.workspace_id AND t.version = NEW.version - 1 AND t.to_status = NEW.from_status AND t.occurred_at <= NEW.occurred_at)) OR (NEW.attempt_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM publication_attempts a WHERE a.id = NEW.attempt_id AND a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id AND a.number = (SELECT max(x.number) FROM publication_attempts x WHERE x.publication_id = NEW.publication_id AND x.workspace_id = NEW.workspace_id) AND ((NEW.operation IN ('start', 'retry') AND a.started_at = NEW.occurred_at) OR (NEW.outcome IS NOT NULL AND a.started_at <= NEW.observed_at)))) OR (NEW.observed_at IS NOT NULL AND NEW.version > 1 AND NEW.observed_at < (SELECT t.occurred_at FROM publication_transitions t WHERE t.publication_id = NEW.publication_id AND t.workspace_id = NEW.workspace_id AND t.version = NEW.version - 1))",
        },
    }
    statements = []
    for table, operations in checks.items():
        for operation, condition in operations.items():
            name = f"{table}_{operation.lower()}_guard"
            if dialect == "postgresql":
                # Lock the aggregate before checking attempt order, even for direct SQL inserts.
                lock = (
                    "PERFORM 1 FROM publications WHERE id = NEW.publication_id AND workspace_id = NEW.workspace_id FOR UPDATE;"
                    if table != "publications" and operation == "INSERT"
                    else ""
                )
                statements.extend(
                    [
                        f"CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {lock} IF {condition} THEN RAISE EXCEPTION 'Invalid or immutable publishing history'; END IF; RETURN NEW; END $$",
                        f"CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}()",
                    ]
                )
            else:
                statements.append(
                    f"CREATE TRIGGER {name} BEFORE {operation} ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT, 'Invalid or immutable publishing history'); END"
                )
    if dialect == "postgresql":
        statements.extend(
            [
                """CREATE FUNCTION publication_projection_guard() RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE p publications%ROWTYPE; t publication_transitions%ROWTYPE;
            BEGIN
              IF TG_TABLE_NAME = 'publications' THEN
                SELECT * INTO p FROM publications WHERE id = NEW.id;
              ELSE
                SELECT * INTO p FROM publications WHERE id = NEW.publication_id;
              END IF;
              IF p.transition_version != (SELECT count(*) FROM publication_transitions
                  WHERE publication_id = p.id AND workspace_id = p.workspace_id) THEN
                RAISE EXCEPTION 'Publication projection requires complete history';
              END IF;
              IF p.transition_version > 0 THEN
                SELECT * INTO t FROM publication_transitions
                  WHERE publication_id = p.id AND workspace_id = p.workspace_id
                  AND version = p.transition_version;
                IF t.id IS NULL OR t.to_status != p.status OR t.occurred_at != p.updated_at
                  OR (p.status = 'published' AND
                    (p.external_post_id IS DISTINCT FROM t.external_post_id
                     OR p.published_at IS DISTINCT FROM t.observed_at)) THEN
                  RAISE EXCEPTION 'Publication projection differs from history';
                END IF;
              END IF;
              IF EXISTS (SELECT 1 FROM publication_attempts a
                WHERE a.publication_id = p.id AND NOT EXISTS
                (SELECT 1 FROM publication_transitions h WHERE h.attempt_id = a.id
                 AND h.operation IN ('start', 'retry'))) THEN
                RAISE EXCEPTION 'Attempt requires committed start history';
              END IF;
              RETURN NULL;
            END $$""",
                *[
                    f"CREATE CONSTRAINT TRIGGER {table}_projection_guard AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION publication_projection_guard()"
                    for table in (
                        "publications",
                        "publication_attempts",
                        "publication_transitions",
                    )
                ],
            ]
        )
    return statements


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_index(
        "uq_scheduling_jobs_publication_scope",
        "scheduling_jobs",
        [
            "id",
            "workspace_id",
            "marketing_content_item_id",
            "marketing_content_item_channel_id",
            "social_account_connection_id",
            "approval_request_id",
            "authorized_content_revision",
            "schedule_generation",
        ],
        unique=True,
    )
    op.create_index(
        "uq_social_accounts_publication_provider",
        "social_account_connections",
        ["id", "organization_id", "provider"],
        unique=True,
    )
    op.create_table(
        "publications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("scheduling_job_id", sa.Uuid(), nullable=False),
        sa.Column("marketing_content_item_id", sa.Uuid(), nullable=False),
        sa.Column("marketing_content_item_channel_id", sa.Uuid(), nullable=False),
        sa.Column("social_account_connection_id", sa.Uuid(), nullable=False),
        sa.Column("approval_request_id", sa.Uuid(), nullable=False),
        sa.Column("authorized_content_revision", sa.Integer(), nullable=False),
        sa.Column("schedule_generation", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="pending", nullable=False
        ),
        sa.Column(
            "transition_version", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("canonical_envelope", sa.LargeBinary(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("external_post_id", sa.String(length=512), nullable=True),
        sa.Column("provider_url", sa.String(length=2048), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=40), nullable=True),
        sa.Column("manual_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual_action_reason", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(status = 'cancelled' AND cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL AND cancellation_reason = 'scheduling_cancelled') OR (status != 'cancelled' AND cancelled_at IS NULL AND cancellation_reason IS NULL)",
            name=op.f("ck_publications_cancellation"),
        ),
        sa.CheckConstraint(
            "(status = 'manual_action_required' AND manual_action_at IS NOT NULL AND manual_action_reason IS NOT NULL AND manual_action_reason = 'outcome_unknown') OR (status != 'manual_action_required' AND manual_action_at IS NULL AND manual_action_reason IS NULL)",
            name=op.f("ck_publications_manual_action"),
        ),
        sa.CheckConstraint(
            "(status = 'published' AND published_at IS NOT NULL AND external_post_id IS NOT NULL AND length(trim(external_post_id)) > 0 AND length(external_post_id) <= 512) OR (status != 'published' AND published_at IS NULL AND external_post_id IS NULL AND provider_url IS NULL)",
            name=op.f("ck_publications_publication_evidence"),
        ),
        sa.CheckConstraint(
            "provider_url IS NULL OR (provider_url LIKE 'https://%' AND provider_url NOT LIKE '%?%' AND provider_url NOT LIKE '%#%' AND provider_url NOT LIKE '%@%')",
            name=op.f("ck_publications_public_url"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'published', 'retryable_failure', 'retrying', 'permanent_failure', 'manual_action_required', 'cancelled')",
            name=op.f("ck_publications_status"),
        ),
        sa.CheckConstraint(
            "length(payload_fingerprint) = 64 AND length(canonical_envelope) > 0 AND length(canonical_envelope) <= 25169920",
            name=op.f("ck_publications_envelope"),
        ),
        sa.CheckConstraint(
            "transition_version >= 0 AND authorized_content_revision > 0 AND schedule_generation > 0 AND payload_schema_version = 1",
            name=op.f("ck_publications_versions"),
        ),
        sa.CheckConstraint(
            "updated_at >= created_at AND (published_at IS NULL OR published_at >= created_at) AND (cancelled_at IS NULL OR cancelled_at >= created_at) AND (manual_action_at IS NULL OR manual_action_at >= created_at)",
            name=op.f("ck_publications_chronology"),
        ),
        sa.ForeignKeyConstraint(
            [
                "scheduling_job_id",
                "workspace_id",
                "marketing_content_item_id",
                "marketing_content_item_channel_id",
                "social_account_connection_id",
                "approval_request_id",
                "authorized_content_revision",
                "schedule_generation",
            ],
            [
                "scheduling_jobs.id",
                "scheduling_jobs.workspace_id",
                "scheduling_jobs.marketing_content_item_id",
                "scheduling_jobs.marketing_content_item_channel_id",
                "scheduling_jobs.social_account_connection_id",
                "scheduling_jobs.approval_request_id",
                "scheduling_jobs.authorized_content_revision",
                "scheduling_jobs.schedule_generation",
            ],
            name="fk_publications_job_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["social_account_connection_id", "workspace_id", "provider"],
            [
                "social_account_connections.id",
                "social_account_connections.organization_id",
                "social_account_connections.provider",
            ],
            name="fk_publications_provider_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["organizations.id"],
            name=op.f("fk_publications_workspace_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publications")),
        sa.UniqueConstraint("id", "workspace_id", name="uq_publications_scope"),
        sa.UniqueConstraint("receipt_id", name="uq_publications_receipt"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_publications_idempotency"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "marketing_content_item_channel_id",
            "authorized_content_revision",
            "schedule_generation",
            name="uq_publications_intent",
        ),
        sa.UniqueConstraint(
            "workspace_id", "scheduling_job_id", name="uq_publications_job"
        ),
    )
    op.create_index(
        "ix_publications_content",
        "publications",
        ["workspace_id", "marketing_content_item_id"],
        unique=False,
    )
    op.create_index(
        "ix_publications_destination",
        "publications",
        ["social_account_connection_id"],
        unique=False,
    )
    op.create_index(
        "ix_publications_workspace_status",
        "publications",
        ["workspace_id", "status", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "uq_publications_provider_resource",
        "publications",
        ["workspace_id", "social_account_connection_id", "external_post_id"],
        unique=True,
        postgresql_where=sa.text("external_post_id IS NOT NULL"),
        sqlite_where=sa.text("external_post_id IS NOT NULL"),
    )
    op.create_table(
        "publication_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("publication_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("number > 0", name=op.f("ck_publication_attempts_number")),
        sa.ForeignKeyConstraint(
            ["publication_id", "workspace_id"],
            ["publications.id", "publications.workspace_id"],
            name="fk_publication_attempts_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_attempts")),
        sa.UniqueConstraint(
            "id", "publication_id", "workspace_id", name="uq_publication_attempts_scope"
        ),
        sa.UniqueConstraint(
            "workspace_id", "execution_id", name="uq_publication_attempts_execution"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "publication_id",
            "number",
            name="uq_publication_attempts_number",
        ),
    )
    op.create_table(
        "publication_transitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("publication_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=False),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("failure_reason", sa.String(length=40), nullable=True),
        sa.Column("external_post_id", sa.String(length=512), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(operation = 'start' AND from_status = 'pending' AND to_status = 'processing') OR (operation = 'retry' AND from_status = 'retryable_failure' AND to_status = 'retrying') OR (operation = 'cancel' AND from_status IN ('pending', 'retryable_failure') AND to_status = 'cancelled') OR (from_status IN ('processing', 'retrying', 'manual_action_required') AND (from_status != 'manual_action_required' OR source = 'reconciliation') AND ((operation = 'confirm_success' AND outcome = 'published' AND to_status = 'published') OR (operation = 'fail_retryable' AND outcome = 'retryable_failure' AND to_status = 'retryable_failure') OR (operation = 'fail_permanently' AND outcome = 'permanent_failure' AND to_status = 'permanent_failure') OR (operation = 'require_manual_action' AND outcome = 'unknown' AND to_status = 'manual_action_required' AND from_status != 'manual_action_required')))",
            name=op.f("ck_publication_transitions_edge"),
        ),
        sa.CheckConstraint(
            "(operation IN ('start', 'retry') AND attempt_id IS NOT NULL AND outcome IS NULL AND observed_at IS NULL AND source IS NULL AND failure_reason IS NULL AND external_post_id IS NULL) OR (operation = 'cancel' AND attempt_id IS NULL AND outcome IS NULL AND observed_at IS NULL AND source IS NULL AND failure_reason IS NULL AND external_post_id IS NULL) OR (operation NOT IN ('start', 'retry', 'cancel') AND attempt_id IS NOT NULL AND outcome IS NOT NULL AND observed_at IS NOT NULL AND source IS NOT NULL)",
            name=op.f("ck_publication_transitions_shape"),
        ),
        sa.CheckConstraint(
            "failure_reason IN ('temporary_unavailability', 'rate_limited', 'invalid_content', 'destination_unavailable', 'authorization_required', 'outcome_unknown')",
            name=op.f("ck_publication_transitions_reason"),
        ),
        sa.CheckConstraint(
            "from_status IN ('pending', 'processing', 'published', 'retryable_failure', 'retrying', 'permanent_failure', 'manual_action_required', 'cancelled')",
            name=op.f("ck_publication_transitions_from_status"),
        ),
        sa.CheckConstraint(
            "operation IN ('start', 'retry', 'confirm_success', 'fail_retryable', 'fail_permanently', 'require_manual_action', 'cancel')",
            name=op.f("ck_publication_transitions_operation"),
        ),
        sa.CheckConstraint(
            "outcome IN ('published', 'retryable_failure', 'permanent_failure', 'unknown')",
            name=op.f("ck_publication_transitions_outcome"),
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR (outcome = 'published' AND external_post_id IS NOT NULL AND length(trim(external_post_id)) > 0 AND length(external_post_id) <= 512 AND failure_reason IS NULL) OR (outcome != 'published' AND external_post_id IS NULL AND failure_reason IS NOT NULL AND ((outcome = 'unknown' AND failure_reason = 'outcome_unknown') OR (outcome != 'unknown' AND failure_reason != 'outcome_unknown')))",
            name=op.f("ck_publication_transitions_evidence"),
        ),
        sa.CheckConstraint(
            "source != 'execution_interrupted' OR outcome = 'unknown'",
            name=op.f("ck_publication_transitions_interruption"),
        ),
        sa.CheckConstraint(
            "source IN ('provider_response', 'reconciliation', 'execution_interrupted')",
            name=op.f("ck_publication_transitions_source"),
        ),
        sa.CheckConstraint(
            "to_status IN ('pending', 'processing', 'published', 'retryable_failure', 'retrying', 'permanent_failure', 'manual_action_required', 'cancelled')",
            name=op.f("ck_publication_transitions_to_status"),
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599 AND outcome IS NOT NULL)",
            name=op.f("ck_publication_transitions_http_status"),
        ),
        sa.CheckConstraint(
            "observed_at IS NULL OR observed_at <= occurred_at",
            name=op.f("ck_publication_transitions_chronology"),
        ),
        sa.CheckConstraint(
            "version > 0", name=op.f("ck_publication_transitions_version")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "publication_id", "workspace_id"],
            [
                "publication_attempts.id",
                "publication_attempts.publication_id",
                "publication_attempts.workspace_id",
            ],
            name="fk_publication_transitions_attempt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id", "workspace_id"],
            ["publications.id", "publications.workspace_id"],
            name="fk_publication_transitions_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_transitions")),
        sa.UniqueConstraint(
            "workspace_id", "operation_id", name="uq_publication_transitions_operation"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "publication_id",
            "version",
            name="uq_publication_transitions_version",
        ),
    )
    op.create_index(
        "ix_publication_transitions_attempt",
        "publication_transitions",
        ["workspace_id", "publication_id", "attempt_id", "version"],
        unique=False,
    )
    op.create_index(
        "uq_publication_transitions_attempt_start",
        "publication_transitions",
        ["attempt_id"],
        unique=True,
        postgresql_where=sa.text("operation IN ('start', 'retry')"),
        sqlite_where=sa.text("operation IN ('start', 'retry')"),
    )
    # ### end Alembic commands ###
    for statement in guard_statements(op.get_bind().dialect.name):
        op.execute(statement)


def downgrade():
    op.drop_table("publication_transitions")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS publication_transitions_insert_guard()")
        op.execute("DROP FUNCTION IF EXISTS publication_transitions_update_guard()")
        op.execute("DROP FUNCTION IF EXISTS publication_transitions_delete_guard()")
    op.drop_table("publication_attempts")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS publication_attempts_insert_guard()")
        op.execute("DROP FUNCTION IF EXISTS publication_attempts_update_guard()")
        op.execute("DROP FUNCTION IF EXISTS publication_attempts_delete_guard()")
    op.drop_table("publications")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS publications_insert_guard()")
        op.execute("DROP FUNCTION IF EXISTS publications_update_guard()")
        op.execute("DROP FUNCTION IF EXISTS publications_delete_guard()")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS publication_projection_guard()")
    op.drop_index(
        "uq_social_accounts_publication_provider",
        table_name="social_account_connections",
    )
    op.drop_index("uq_scheduling_jobs_publication_scope", table_name="scheduling_jobs")
