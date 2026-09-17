"""Bind accepted delivery to a stable external destination identity.

Null legacy bindings are retained for history and cannot execute via Stage 3.
Guard SQL is frozen here; no mutable application imports.
"""

import sqlalchemy as sa
from alembic import op

revision = "202609162300"
down_revision = "202609162200"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "publications", sa.Column("destination_identity", sa.String(64), nullable=True)
    )
    op.execute(NEW_GUARD)


def downgrade():
    op.execute(OLD_GUARD)
    op.drop_column("publications", "destination_identity")


OLD_GUARD = "CREATE OR REPLACE FUNCTION publications_update_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN  IF (OLD.id IS DISTINCT FROM NEW.id OR OLD.workspace_id IS DISTINCT FROM NEW.workspace_id OR OLD.scheduling_job_id IS DISTINCT FROM NEW.scheduling_job_id OR OLD.marketing_content_item_id IS DISTINCT FROM NEW.marketing_content_item_id OR OLD.marketing_content_item_channel_id IS DISTINCT FROM NEW.marketing_content_item_channel_id OR OLD.social_account_connection_id IS DISTINCT FROM NEW.social_account_connection_id OR OLD.approval_request_id IS DISTINCT FROM NEW.approval_request_id OR OLD.authorized_content_revision IS DISTINCT FROM NEW.authorized_content_revision OR OLD.schedule_generation IS DISTINCT FROM NEW.schedule_generation OR OLD.provider IS DISTINCT FROM NEW.provider OR OLD.receipt_id IS DISTINCT FROM NEW.receipt_id OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key OR OLD.payload_schema_version IS DISTINCT FROM NEW.payload_schema_version OR OLD.payload_fingerprint IS DISTINCT FROM NEW.payload_fingerprint OR OLD.canonical_envelope IS DISTINCT FROM NEW.canonical_envelope OR OLD.correlation_id IS DISTINCT FROM NEW.correlation_id OR OLD.created_at IS DISTINCT FROM NEW.created_at) OR OLD.status IN ('published', 'permanent_failure', 'cancelled') OR NEW.transition_version != OLD.transition_version + 1 OR NEW.updated_at < OLD.updated_at OR NOT ((OLD.status = 'pending' AND NEW.status IN ('processing', 'cancelled')) OR (OLD.status = 'retryable_failure' AND NEW.status IN ('retrying', 'cancelled')) OR (OLD.status IN ('processing', 'retrying') AND NEW.status IN ('published', 'retryable_failure', 'permanent_failure', 'manual_action_required')) OR (OLD.status = 'manual_action_required' AND NEW.status IN ('published', 'retryable_failure', 'permanent_failure'))) THEN RAISE EXCEPTION 'Invalid or immutable publishing history'; END IF; RETURN NEW; END $$"

NEW_GUARD = "CREATE OR REPLACE FUNCTION publications_update_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN  IF (OLD.id IS DISTINCT FROM NEW.id OR OLD.workspace_id IS DISTINCT FROM NEW.workspace_id OR OLD.scheduling_job_id IS DISTINCT FROM NEW.scheduling_job_id OR OLD.marketing_content_item_id IS DISTINCT FROM NEW.marketing_content_item_id OR OLD.marketing_content_item_channel_id IS DISTINCT FROM NEW.marketing_content_item_channel_id OR OLD.social_account_connection_id IS DISTINCT FROM NEW.social_account_connection_id OR OLD.approval_request_id IS DISTINCT FROM NEW.approval_request_id OR OLD.authorized_content_revision IS DISTINCT FROM NEW.authorized_content_revision OR OLD.schedule_generation IS DISTINCT FROM NEW.schedule_generation OR OLD.provider IS DISTINCT FROM NEW.provider OR OLD.destination_identity IS DISTINCT FROM NEW.destination_identity OR OLD.receipt_id IS DISTINCT FROM NEW.receipt_id OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key OR OLD.payload_schema_version IS DISTINCT FROM NEW.payload_schema_version OR OLD.payload_fingerprint IS DISTINCT FROM NEW.payload_fingerprint OR OLD.canonical_envelope IS DISTINCT FROM NEW.canonical_envelope OR OLD.correlation_id IS DISTINCT FROM NEW.correlation_id OR OLD.created_at IS DISTINCT FROM NEW.created_at) OR OLD.status IN ('published', 'permanent_failure', 'cancelled') OR NEW.transition_version != OLD.transition_version + 1 OR NEW.updated_at < OLD.updated_at OR NOT ((OLD.status = 'pending' AND NEW.status IN ('processing', 'cancelled')) OR (OLD.status = 'retryable_failure' AND NEW.status IN ('retrying', 'cancelled')) OR (OLD.status IN ('processing', 'retrying') AND NEW.status IN ('published', 'retryable_failure', 'permanent_failure', 'manual_action_required')) OR (OLD.status = 'manual_action_required' AND NEW.status IN ('published', 'retryable_failure', 'permanent_failure'))) THEN RAISE EXCEPTION 'Invalid or immutable publishing history'; END IF; RETURN NEW; END $$"
