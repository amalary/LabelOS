"""Stage 9: independent Publishing execution leases and monotonic fences."""

import sqlalchemy as sa
from alembic import op

revision = "202609170200"
down_revision = "202609170100"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "publication_leases",
        sa.Column("publication_id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interrupted", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(
            ["publication_id", "workspace_id"],
            ["publications.id", "publications.workspace_id"],
            name="fk_publication_leases_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("fencing_token >= 0", name="fence"),
        sa.CheckConstraint(
            "(owner_id IS NULL AND expires_at IS NULL) OR "
            "(owner_id IS NOT NULL AND expires_at IS NOT NULL AND fencing_token > 0)",
            name="ownership",
        ),
    )
    op.create_index(
        "ix_publication_leases_expiry",
        "publication_leases",
        ["workspace_id", "expires_at"],
    )
    # Existing unfenced processing attempts require the established stopped-host
    # recovery procedure. Do not pretend migration established their ownership.
    op.execute(
        "INSERT INTO publication_leases (publication_id, workspace_id) "
        "SELECT id, workspace_id FROM publications"
    )


def downgrade():
    op.drop_table("publication_leases")
