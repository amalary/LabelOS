"""Append-only dataset documentation lifecycle.

Revision ID: 202610120200
Revises: 202610120100
"""

import sqlalchemy as sa
from alembic import op

revision = "202610120200"
down_revision = "202610120100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Column-local checks support SQLite ALTER ADD without rebuilding an immutable
    # table referenced by collection runs. PostgreSQL supports the same DDL.
    op.add_column(
        "dataset_documentation",
        sa.Column(
            "state",
            sa.String(20),
            sa.CheckConstraint(
                "state IN ('draft', 'validated', 'published')",
                name=op.f("ck_dataset_documentation_state"),
            ),
            nullable=False,
            server_default="draft",
        ),
    )
    op.add_column(
        "dataset_documentation",
        sa.Column(
            "authored_revision",
            sa.Integer(),
            sa.CheckConstraint(
                "authored_revision IS NULL OR "
                "(authored_revision > 0 AND authored_revision <= revision)",
                name=op.f("ck_dataset_documentation_authored_revision"),
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT 1 FROM dataset_documentation WHERE state != 'draft' "
            "OR (authored_revision IS NOT NULL AND authored_revision != revision) LIMIT 1"
        )
    ):
        raise RuntimeError("Documentation review history prevents downgrade")
    op.drop_column("dataset_documentation", "authored_revision")
    op.drop_column("dataset_documentation", "state")
