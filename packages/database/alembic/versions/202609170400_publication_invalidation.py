"""Allow terminal cancellation of withdrawn approval or superseded intent."""

from alembic import op

revision = "202609170400"
down_revision = "202609170300"
branch_labels = None
depends_on = None

OLD_CHECK = "(status = 'cancelled' AND cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL AND cancellation_reason = 'scheduling_cancelled') OR (status != 'cancelled' AND cancelled_at IS NULL AND cancellation_reason IS NULL)"
NEW_CHECK = "(status = 'cancelled' AND cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL AND cancellation_reason IN ('scheduling_cancelled', 'stale_approval', 'stale_content_revision', 'ineligible_parent_state', 'changed_schedule_generation', 'missing_schedule_intent')) OR (status != 'cancelled' AND cancelled_at IS NULL AND cancellation_reason IS NULL)"


def upgrade():
    op.drop_constraint(
        op.f("ck_publications_cancellation"), "publications", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_publications_cancellation"), "publications", NEW_CHECK
    )


def downgrade():
    # Intentionally refuse downgrade if invalidation history exists. Rewriting
    # immutable terminal reasons would destroy audit evidence.
    op.drop_constraint(
        op.f("ck_publications_cancellation"), "publications", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_publications_cancellation"), "publications", OLD_CHECK
    )
