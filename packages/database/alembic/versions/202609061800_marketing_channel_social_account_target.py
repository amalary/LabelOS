"""add optional social account target to marketing channels

Revision ID: 202609061800
Revises: 202609061500
Create Date: 2026-09-06 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609061800"
down_revision: str | None = "202609061500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("marketing_content_item_channels") as batch_op:
        batch_op.add_column(
            sa.Column("social_account_connection_id", sa.Uuid(), nullable=True),
        )
        batch_op.create_foreign_key(
            op.f(
                "fk_marketing_content_item_channels_social_account_connection_id_social_account_connections"
            ),
            "social_account_connections",
            ["social_account_connection_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_marketing_content_item_channels_social_account_connection_id",
        "marketing_content_item_channels",
        ["social_account_connection_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketing_content_item_channels_social_account_connection_id",
        table_name="marketing_content_item_channels",
    )
    with op.batch_alter_table("marketing_content_item_channels") as batch_op:
        batch_op.drop_constraint(
            op.f(
                "fk_marketing_content_item_channels_social_account_connection_id_social_account_connections"
            ),
            type_="foreignkey",
        )
        batch_op.drop_column("social_account_connection_id")
