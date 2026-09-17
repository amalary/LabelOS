"""Stage 8 durable normalized failures and bounded retry eligibility.

Legacy failures retain history and remain fail-closed (no automatic retry time).
Policy/guard SQL is frozen; upgrades do not rewrite immutable observations.
"""

import sqlalchemy as sa
from alembic import op

revision = "202609170100"
down_revision = "202609162300"
branch_labels = None
depends_on = None

CHECKS = [
    (
        "retry_category",
        "failure_category IS NULL OR failure_category IN ('transient_network', 'provider_unavailable', 'rate_limited', 'authentication', 'authorization', 'invalid_content_media', 'unsupported_operation', 'ambiguous_outcome', 'permanent_rejection', 'internal_failure')",
    ),
    (
        "retry_disposition",
        "retry_disposition IS NULL OR retry_disposition IN ('automatic', 'provider_delay', 'blocked_reconnection', 'reconciliation_required', 'permanent', 'manual_action', 'exhausted')",
    ),
    ("retry_policy", "retry_policy_version IS NULL OR retry_policy_version = 1"),
    (
        "retry_schedule",
        "(next_retry_at IS NULL AND (retry_disposition IS NULL OR retry_disposition NOT IN ('automatic', 'provider_delay'))) OR (next_retry_at IS NOT NULL AND retry_disposition IS NOT NULL AND retry_disposition IN ('automatic', 'provider_delay') AND retry_deadline_at IS NOT NULL AND next_retry_at < retry_deadline_at AND failure_category IS NOT NULL AND failure_category IN ('transient_network', 'provider_unavailable', 'rate_limited') AND retry_policy_version IS NOT NULL AND retry_policy_version = 1)",
    ),
]
OLD_FUNCTIONS = [
    "CREATE OR REPLACE FUNCTION publication_attempts_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM 1 FROM publications WHERE id = NEW.publication_id AND workspace_id = NEW.workspace_id FOR UPDATE; IF NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id AND p.workspace_id = NEW.workspace_id AND p.status IN ('pending', 'retryable_failure') AND NEW.started_at >= p.updated_at) OR NEW.number != (SELECT count(*) + 1 FROM publication_attempts a WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id) OR (NEW.number > 1 AND NOT EXISTS (SELECT 1 FROM publication_transitions t JOIN publication_attempts a ON a.id = t.attempt_id WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id AND a.number = NEW.number - 1 AND t.outcome = 'retryable_failure' AND t.version = (SELECT max(x.version) FROM publication_transitions x WHERE x.publication_id = NEW.publication_id AND x.workspace_id = NEW.workspace_id))) THEN RAISE EXCEPTION 'Invalid or immutable publishing history'; END IF; RETURN NEW; END $$",
    "CREATE OR REPLACE FUNCTION publication_projection_guard() RETURNS trigger\n            LANGUAGE plpgsql AS $$\n            DECLARE p publications%ROWTYPE; t publication_transitions%ROWTYPE;\n            BEGIN\n              IF TG_TABLE_NAME = 'publications' THEN\n                SELECT * INTO p FROM publications WHERE id = NEW.id;\n              ELSE\n                SELECT * INTO p FROM publications WHERE id = NEW.publication_id;\n              END IF;\n              IF p.transition_version != (SELECT count(*) FROM publication_transitions\n                  WHERE publication_id = p.id AND workspace_id = p.workspace_id) THEN\n                RAISE EXCEPTION 'Publication projection requires complete history';\n              END IF;\n              IF p.transition_version > 0 THEN\n                SELECT * INTO t FROM publication_transitions\n                  WHERE publication_id = p.id AND workspace_id = p.workspace_id\n                  AND version = p.transition_version;\n                IF t.id IS NULL OR t.to_status != p.status OR t.occurred_at != p.updated_at\n                  OR (p.status = 'published' AND\n                    (p.external_post_id IS DISTINCT FROM t.external_post_id\n                     OR p.published_at IS DISTINCT FROM t.observed_at)) THEN\n                  RAISE EXCEPTION 'Publication projection differs from history';\n                END IF;\n              END IF;\n              IF EXISTS (SELECT 1 FROM publication_attempts a\n                WHERE a.publication_id = p.id AND NOT EXISTS\n                (SELECT 1 FROM publication_transitions h WHERE h.attempt_id = a.id\n                 AND h.operation IN ('start', 'retry'))) THEN\n                RAISE EXCEPTION 'Attempt requires committed start history';\n              END IF;\n              RETURN NULL;\n            END $$",
]
NEW_FUNCTIONS = [
    "CREATE OR REPLACE FUNCTION publication_attempts_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM 1 FROM publications WHERE id = NEW.publication_id AND workspace_id = NEW.workspace_id FOR UPDATE; IF NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id AND p.workspace_id = NEW.workspace_id AND p.status IN ('pending', 'retryable_failure') AND NEW.started_at >= p.updated_at AND (p.status = 'pending' OR (p.retry_policy_version = 1 AND p.retry_disposition IN ('automatic', 'provider_delay') AND p.next_retry_at <= NEW.started_at AND p.retry_deadline_at > NEW.started_at AND NEW.number <= 5))) OR NEW.number != (SELECT count(*) + 1 FROM publication_attempts a WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id) OR (NEW.number > 1 AND NOT EXISTS (SELECT 1 FROM publication_transitions t JOIN publication_attempts a ON a.id = t.attempt_id WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id AND a.number = NEW.number - 1 AND t.outcome = 'retryable_failure' AND t.version = (SELECT max(x.version) FROM publication_transitions x WHERE x.publication_id = NEW.publication_id AND x.workspace_id = NEW.workspace_id))) THEN RAISE EXCEPTION 'Invalid or immutable publishing history'; END IF; RETURN NEW; END $$",
    "CREATE OR REPLACE FUNCTION publication_projection_guard() RETURNS trigger\n            LANGUAGE plpgsql AS $$\n            DECLARE p publications%ROWTYPE; t publication_transitions%ROWTYPE;\n            BEGIN\n              IF TG_TABLE_NAME = 'publications' THEN\n                SELECT * INTO p FROM publications WHERE id = NEW.id;\n              ELSE\n                SELECT * INTO p FROM publications WHERE id = NEW.publication_id;\n              END IF;\n              IF p.transition_version != (SELECT count(*) FROM publication_transitions\n                  WHERE publication_id = p.id AND workspace_id = p.workspace_id) THEN\n                RAISE EXCEPTION 'Publication projection requires complete history';\n              END IF;\n              IF p.transition_version > 0 THEN\n                SELECT * INTO t FROM publication_transitions\n                  WHERE publication_id = p.id AND workspace_id = p.workspace_id\n                  AND version = p.transition_version;\n                IF t.id IS NULL OR t.to_status != p.status OR t.occurred_at != p.updated_at\n                  OR p.failure_category IS DISTINCT FROM t.failure_category\n                  OR p.retry_disposition IS DISTINCT FROM t.retry_disposition\n                  OR p.next_retry_at IS DISTINCT FROM t.next_retry_at\n                  OR p.retry_deadline_at IS DISTINCT FROM t.retry_deadline_at\n                  OR p.retry_policy_version IS DISTINCT FROM t.retry_policy_version\n                  OR (p.status = 'published' AND\n                    (p.external_post_id IS DISTINCT FROM t.external_post_id\n                     OR p.published_at IS DISTINCT FROM t.observed_at)) THEN\n                  RAISE EXCEPTION 'Publication projection differs from history';\n                END IF;\n              END IF;\n              IF EXISTS (SELECT 1 FROM publication_attempts a\n                WHERE a.publication_id = p.id AND NOT EXISTS\n                (SELECT 1 FROM publication_transitions h WHERE h.attempt_id = a.id\n                 AND h.operation IN ('start', 'retry'))) THEN\n                RAISE EXCEPTION 'Attempt requires committed start history';\n              END IF;\n              RETURN NULL;\n            END $$",
]


def upgrade():
    for table in ("publications", "publication_transitions"):
        for name, type_ in (
            ("failure_category", sa.String(40)),
            ("retry_disposition", sa.String(32)),
            ("next_retry_at", sa.DateTime(timezone=True)),
            ("retry_deadline_at", sa.DateTime(timezone=True)),
            ("retry_policy_version", sa.Integer()),
        ):
            op.add_column(table, sa.Column(name, type_, nullable=True))
        for name, sql in CHECKS:
            op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, sql)
    op.add_column(
        "publication_transitions",
        sa.Column("retry_after_seconds", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_publications_retry_state"),
        "publications",
        "next_retry_at IS NULL OR (status = 'retryable_failure' AND next_retry_at >= updated_at)",
    )
    op.create_check_constraint(
        op.f("ck_publication_transitions_retry_hint"),
        "publication_transitions",
        "retry_after_seconds IS NULL OR (retry_after_seconds >= 0 AND retry_after_seconds <= 604800 AND outcome = 'retryable_failure')",
    )
    op.create_index(
        "ix_publications_retry_due",
        "publications",
        ["workspace_id", "next_retry_at", "id"],
    )
    for statement in NEW_FUNCTIONS:
        op.execute(statement)


def downgrade():
    for statement in OLD_FUNCTIONS:
        op.execute(statement)
    op.drop_index("ix_publications_retry_due", table_name="publications")
    op.drop_constraint(
        op.f("ck_publications_retry_state"), "publications", type_="check"
    )
    op.drop_constraint(
        op.f("ck_publication_transitions_retry_hint"),
        "publication_transitions",
        type_="check",
    )
    op.drop_column("publication_transitions", "retry_after_seconds")
    for table in ("publications", "publication_transitions"):
        for name, _ in CHECKS:
            op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
        for name in (
            "failure_category",
            "retry_disposition",
            "next_retry_at",
            "retry_deadline_at",
            "retry_policy_version",
        ):
            op.drop_column(table, name)
