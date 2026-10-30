"""Human shortlist and separately expiring YouTube source links."""

import sqlalchemy as sa
from alembic import op

revision = "202610270200"
down_revision = "202610270100"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scouting_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('new', 'reviewing', 'shortlisted', 'passed')",
            name="review_status",
        ),
    )
    op.create_index(
        "ix_scouting_candidates_workspace_id", "scouting_candidates", ["workspace_id"]
    )
    op.create_table(
        "scouting_sources",
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("channel_id", sa.String(24), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            sa.ForeignKey(
                "scouting_candidates.id",
                ondelete="CASCADE",
                deferrable=True,
                initially="DEFERRED",
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_id"),
    )
    op.create_index(
        "ix_scouting_sources_expires_at", "scouting_sources", ["expires_at"]
    )


def downgrade():
    raise RuntimeError(
        "Shortlist deletion requires an explicit data retention decision"
    )
