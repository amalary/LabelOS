"""Add content-free, shared YouTube request budgets; explicit opt-in required.

Revision ID: 202610270100
Revises: 202610130100
"""

import sqlalchemy as sa
from alembic import context, op

revision = "202610270100"
down_revision = "202610130100"
branch_labels = None
depends_on = None


def upgrade():
    if (
        context.get_x_argument(as_dictionary=True).get("youtube_quota_approved")
        != "true"
    ):
        raise RuntimeError(
            "Approve the target database before using -x youtube_quota_approved=true"
        )
    op.create_table(
        "youtube_quota_buckets",
        sa.Column("bucket", sa.String(16), primary_key=True),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.Column("reset_at", sa.BigInteger(), nullable=False),
        sa.Column("next_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("bucket IN ('search', 'channels')", name="valid_bucket"),
        sa.CheckConstraint("used >= 0", name="nonnegative_usage"),
    )


def downgrade():
    raise RuntimeError("Quota history must not be reset by automatic downgrade")
