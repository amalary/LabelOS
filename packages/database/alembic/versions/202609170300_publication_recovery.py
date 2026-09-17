"""Stage 10: immutable human publication resolution and bounded recovery grants."""

import sqlalchemy as sa
from alembic import op

revision = "202609170300"
down_revision = "202609170200"
branch_labels = None
depends_on = None


def action_guard_statements(dialect):
    previous = "(SELECT h.operation FROM publication_actions h WHERE h.publication_id = NEW.publication_id ORDER BY h.version DESC LIMIT 1)"
    deadline = (
        "NEW.retry_until <= a.started_at + interval '24 hours'"
        if dialect == "postgresql"
        else "julianday(NEW.retry_until) <= julianday(a.started_at, '+24 hours')"
    )
    invalid = f"""
      NEW.version != (SELECT count(*) + 1 FROM publication_actions WHERE publication_id = NEW.publication_id)
      OR NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id
        AND p.workspace_id = NEW.workspace_id AND p.transition_version = NEW.publication_version
        AND p.status IN ('retryable_failure', 'permanent_failure') AND p.updated_at <= NEW.occurred_at)
      OR EXISTS (SELECT 1 FROM publication_leases l WHERE l.publication_id = NEW.publication_id
        AND (l.owner_id IS NOT NULL OR l.interrupted))
      OR EXISTS (SELECT 1 FROM publication_actions h WHERE h.publication_id = NEW.publication_id
        AND (h.operation = 'complete_manual' OR h.occurred_at > NEW.occurred_at))
      OR (NEW.operation = 'begin_manual' AND {previous} = 'begin_manual')
      OR (NEW.operation = 'complete_manual' AND COALESCE({previous}, '') != 'begin_manual')
      OR (NEW.operation = 'authorize_retry' AND (
        {previous} = 'begin_manual' OR
        EXISTS (SELECT 1 FROM publication_actions h WHERE h.publication_id = NEW.publication_id
          AND h.publication_version = NEW.publication_version AND h.operation = 'authorize_retry')
        OR NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id
          AND p.status = 'retryable_failure' AND p.retry_disposition IN ('blocked_reconnection', 'manual_action'))
        OR (SELECT count(*) FROM publication_attempts WHERE publication_id = NEW.publication_id) >= 5
        OR NOT EXISTS (SELECT 1 FROM publication_attempts a WHERE a.publication_id = NEW.publication_id
          AND a.number = 1 AND {deadline})))
    """
    statements = []
    for operation, condition in (
        ("insert", invalid),
        ("update", "1 = 1"),
        ("delete", "1 = 1"),
    ):
        name = f"publication_actions_{operation}_guard"
        if dialect == "postgresql":
            lock = (
                "PERFORM 1 FROM publications WHERE id = NEW.publication_id FOR UPDATE;"
                if operation == "insert"
                else ""
            )
            statements.extend(
                [
                    f"CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {lock} IF {condition} THEN RAISE EXCEPTION 'Invalid or immutable publication action'; END IF; RETURN NEW; END $$",
                    f"CREATE TRIGGER {name} BEFORE {operation.upper()} ON publication_actions FOR EACH ROW EXECUTE FUNCTION {name}()",
                ]
            )
        else:
            statements.append(
                f"CREATE TRIGGER {name} BEFORE {operation.upper()} ON publication_actions WHEN {condition} BEGIN SELECT RAISE(ABORT, 'Invalid or immutable publication action'); END"
            )
    return statements


NEW_ATTEMPT_GUARDS = {
    "sqlite": [
        "CREATE TRIGGER publication_attempts_insert_guard BEFORE INSERT ON publication_attempts WHEN (NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id AND p.workspace_id = NEW.workspace_id AND p.status IN ('pending', 'retryable_failure') AND NEW.started_at >= p.updated_at AND (p.status = 'pending' OR ((p.retry_policy_version = 1 AND p.retry_disposition IN ('automatic', 'provider_delay') AND p.next_retry_at <= NEW.started_at AND p.retry_deadline_at > NEW.started_at  OR EXISTS (SELECT 1 FROM publication_actions h WHERE h.publication_id = p.id AND h.publication_version = p.transition_version AND h.operation = 'authorize_retry' AND h.retry_until > NEW.started_at)) AND NEW.number <= 5))) OR NEW.number != (SELECT count(*) + 1 FROM publication_attempts a WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id) OR (NEW.number > 1 AND NOT EXISTS (SELECT 1 FROM publication_transitions t JOIN publication_attempts a ON a.id = t.attempt_id WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id AND a.number = NEW.number - 1 AND t.outcome = 'retryable_failure' AND t.version = (SELECT max(x.version) FROM publication_transitions x WHERE x.publication_id = NEW.publication_id AND x.workspace_id = NEW.workspace_id)))) OR EXISTS (SELECT 1 FROM publication_actions h WHERE h.publication_id = NEW.publication_id AND h.operation IN ('begin_manual', 'complete_manual') AND h.version = (SELECT max(x.version) FROM publication_actions x WHERE x.publication_id = h.publication_id)) BEGIN SELECT RAISE(ABORT, 'Invalid or immutable publishing history'); END"
    ],
    "postgresql": [
        "CREATE FUNCTION publication_attempts_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM 1 FROM publications WHERE id = NEW.publication_id AND workspace_id = NEW.workspace_id FOR UPDATE; IF (NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id AND p.workspace_id = NEW.workspace_id AND p.status IN ('pending', 'retryable_failure') AND NEW.started_at >= p.updated_at AND (p.status = 'pending' OR ((p.retry_policy_version = 1 AND p.retry_disposition IN ('automatic', 'provider_delay') AND p.next_retry_at <= NEW.started_at AND p.retry_deadline_at > NEW.started_at  OR EXISTS (SELECT 1 FROM publication_actions h WHERE h.publication_id = p.id AND h.publication_version = p.transition_version AND h.operation = 'authorize_retry' AND h.retry_until > NEW.started_at)) AND NEW.number <= 5))) OR NEW.number != (SELECT count(*) + 1 FROM publication_attempts a WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id) OR (NEW.number > 1 AND NOT EXISTS (SELECT 1 FROM publication_transitions t JOIN publication_attempts a ON a.id = t.attempt_id WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id AND a.number = NEW.number - 1 AND t.outcome = 'retryable_failure' AND t.version = (SELECT max(x.version) FROM publication_transitions x WHERE x.publication_id = NEW.publication_id AND x.workspace_id = NEW.workspace_id)))) OR EXISTS (SELECT 1 FROM publication_actions h WHERE h.publication_id = NEW.publication_id AND h.operation IN ('begin_manual', 'complete_manual') AND h.version = (SELECT max(x.version) FROM publication_actions x WHERE x.publication_id = h.publication_id)) THEN RAISE EXCEPTION 'Invalid or immutable publishing history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER publication_attempts_insert_guard BEFORE INSERT ON publication_attempts FOR EACH ROW EXECUTE FUNCTION publication_attempts_insert_guard()",
    ],
}
OLD_ATTEMPT_GUARDS = {
    "sqlite": [
        "CREATE TRIGGER publication_attempts_insert_guard BEFORE INSERT ON publication_attempts WHEN NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id AND p.workspace_id = NEW.workspace_id AND p.status IN ('pending', 'retryable_failure') AND NEW.started_at >= p.updated_at AND (p.status = 'pending' OR (p.retry_policy_version = 1 AND p.retry_disposition IN ('automatic', 'provider_delay') AND p.next_retry_at <= NEW.started_at AND p.retry_deadline_at > NEW.started_at AND NEW.number <= 5))) OR NEW.number != (SELECT count(*) + 1 FROM publication_attempts a WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id) OR (NEW.number > 1 AND NOT EXISTS (SELECT 1 FROM publication_transitions t JOIN publication_attempts a ON a.id = t.attempt_id WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id AND a.number = NEW.number - 1 AND t.outcome = 'retryable_failure' AND t.version = (SELECT max(x.version) FROM publication_transitions x WHERE x.publication_id = NEW.publication_id AND x.workspace_id = NEW.workspace_id))) BEGIN SELECT RAISE(ABORT, 'Invalid or immutable publishing history'); END"
    ],
    "postgresql": [
        "CREATE FUNCTION publication_attempts_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM 1 FROM publications WHERE id = NEW.publication_id AND workspace_id = NEW.workspace_id FOR UPDATE; IF NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id AND p.workspace_id = NEW.workspace_id AND p.status IN ('pending', 'retryable_failure') AND NEW.started_at >= p.updated_at AND (p.status = 'pending' OR (p.retry_policy_version = 1 AND p.retry_disposition IN ('automatic', 'provider_delay') AND p.next_retry_at <= NEW.started_at AND p.retry_deadline_at > NEW.started_at AND NEW.number <= 5))) OR NEW.number != (SELECT count(*) + 1 FROM publication_attempts a WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id) OR (NEW.number > 1 AND NOT EXISTS (SELECT 1 FROM publication_transitions t JOIN publication_attempts a ON a.id = t.attempt_id WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id AND a.number = NEW.number - 1 AND t.outcome = 'retryable_failure' AND t.version = (SELECT max(x.version) FROM publication_transitions x WHERE x.publication_id = NEW.publication_id AND x.workspace_id = NEW.workspace_id))) THEN RAISE EXCEPTION 'Invalid or immutable publishing history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER publication_attempts_insert_guard BEFORE INSERT ON publication_attempts FOR EACH ROW EXECUTE FUNCTION publication_attempts_insert_guard()",
    ],
}


def replace_attempt_guard(statements):
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER publication_attempts_insert_guard ON publication_attempts"
        )
        op.execute("DROP FUNCTION publication_attempts_insert_guard()")
    else:
        op.execute("DROP TRIGGER publication_attempts_insert_guard")
    for statement in statements[dialect]:
        op.execute(sa.text(statement))


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "publication_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("publication_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("publication_version", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_post_id", sa.String(length=512), nullable=True),
        sa.Column("provider_url", sa.String(length=2048), nullable=True),
        sa.CheckConstraint(
            "(operation = 'authorize_retry' AND retry_until IS NOT NULL AND retry_until > occurred_at) OR (operation != 'authorize_retry' AND retry_until IS NULL)",
            name=op.f("ck_publication_actions_retry_until"),
        ),
        sa.CheckConstraint(
            "operation = 'complete_manual' OR (external_post_id IS NULL AND provider_url IS NULL)",
            name=op.f("ck_publication_actions_evidence"),
        ),
        sa.CheckConstraint(
            "operation IN ('begin_manual', 'complete_manual', 'authorize_retry')",
            name=op.f("ck_publication_actions_operation"),
        ),
        sa.CheckConstraint(
            "provider_url IS NULL OR (provider_url LIKE 'https://%' AND provider_url NOT LIKE '%?%' AND provider_url NOT LIKE '%#%' AND provider_url NOT LIKE '%@%')",
            name=op.f("ck_publication_actions_public_url"),
        ),
        sa.CheckConstraint(
            "external_post_id IS NULL OR (length(trim(external_post_id)) > 0 AND length(external_post_id) <= 512)",
            name=op.f("ck_publication_actions_external_id"),
        ),
        sa.CheckConstraint(
            "version > 0 AND publication_version > 0",
            name=op.f("ck_publication_actions_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_publication_actions_actor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id", "workspace_id"],
            ["publications.id", "publications.workspace_id"],
            name="fk_publication_actions_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_actions")),
        sa.UniqueConstraint(
            "publication_id", "version", name="uq_publication_actions_version"
        ),
        sa.UniqueConstraint(
            "workspace_id", "operation_id", name="uq_publication_actions_operation"
        ),
    )
    op.create_index(
        "ix_publication_actions_workspace",
        "publication_actions",
        ["workspace_id", "publication_id", "version"],
        unique=False,
    )
    # ### end Alembic commands ###
    for statement in action_guard_statements(op.get_bind().dialect.name):
        op.execute(sa.text(statement))
    replace_attempt_guard(NEW_ATTEMPT_GUARDS)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM publication_actions")):
        raise RuntimeError("Cannot downgrade while publication action history exists")
    replace_attempt_guard(OLD_ATTEMPT_GUARDS)
    op.drop_table("publication_actions")
    if op.get_bind().dialect.name == "postgresql":
        for operation in ("insert", "update", "delete"):
            op.execute(f"DROP FUNCTION publication_actions_{operation}_guard()")
