"""Content-scoped prepared media for production scheduling handoff."""

import sqlalchemy as sa
from alembic import op

revision = "202609210100"
down_revision = "202609170500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketing_media_assets",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("content_item_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "content_item_id", "sha256"),
        sa.ForeignKeyConstraint(
            ["content_item_id", "workspace_id"],
            ["marketing_content_items.id", "marketing_content_items.organization_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("length(sha256) = 64", name="digest_length"),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 16777216 AND length(data) = size_bytes",
            name="bounded_data",
        ),
    )


def downgrade() -> None:
    op.drop_table("marketing_media_assets")
