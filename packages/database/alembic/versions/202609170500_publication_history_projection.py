"""Small accepted metadata and cursor index for publication history."""

import sqlalchemy as sa
from alembic import op

revision = "202609170500"
down_revision = "202609170400"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "publication_list_metadata",
        sa.Column("publication_id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(80), nullable=False),
        sa.Column("placement", sa.String(120), nullable=True),
        sa.ForeignKeyConstraint(
            ["publication_id", "workspace_id"],
            ["publications.id", "publications.workspace_id"],
            name="fk_publication_list_metadata_scope",
            ondelete="RESTRICT",
        ),
    )
    # One-time, database-side backfill. No envelope bytes leave the database and
    # the immutable journal is untouched. Run before deploying the new reader.
    if op.get_bind().dialect.name == "postgresql":
        snapshot = "convert_from(canonical_envelope, 'UTF8')::json"
        channel = f"{snapshot}->'content'->>'channel'"
        placement = f"{snapshot}->'content'->>'placement'"
    else:
        channel = "json_extract(CAST(canonical_envelope AS TEXT), '$.content.channel')"
        placement = (
            "json_extract(CAST(canonical_envelope AS TEXT), '$.content.placement')"
        )
    op.execute(
        sa.text(
            "INSERT INTO publication_list_metadata "
            "(publication_id, workspace_id, channel, placement) "
            f"SELECT id, workspace_id, {channel}, {placement} FROM publications"
        )
    )
    op.drop_index("ix_publications_content", table_name="publications")
    op.create_index(
        "ix_publications_content",
        "publications",
        ["workspace_id", "marketing_content_item_id", "id"],
    )


def downgrade():
    op.drop_table("publication_list_metadata")
    op.drop_index("ix_publications_content", table_name="publications")
    op.create_index(
        "ix_publications_content",
        "publications",
        ["workspace_id", "marketing_content_item_id"],
    )
