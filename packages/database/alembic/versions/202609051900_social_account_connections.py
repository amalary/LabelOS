"""social account connections

Revision ID: 202609051900
Revises: 202609031500
Create Date: 2026-09-05 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609051900"
down_revision: str | None = "202609031500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


social_account_connection_method = postgresql.ENUM(
    "direct_api",
    "third_party",
    "assisted",
    name="social_account_connection_method",
    create_type=False,
)

social_account_connection_status = postgresql.ENUM(
    "pending",
    "connected",
    "limited",
    "reconnect_required",
    "disconnected",
    "error",
    name="social_account_connection_status",
    create_type=False,
)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def upgrade() -> None:
    bind = op.get_bind()
    social_account_connection_method.create(bind, checkfirst=True)
    social_account_connection_status.create(bind, checkfirst=True)

    op.create_table(
        "social_account_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("artist_profile_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("profile_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "connection_method",
            social_account_connection_method,
            server_default="assisted",
            nullable=False,
        ),
        sa.Column(
            "status",
            social_account_connection_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("capabilities", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("credential_ref", sa.String(length=500), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_health_checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_error_code", sa.String(length=120), nullable=True),
        sa.Column("last_error_message", sa.String(length=2000), nullable=True),
        sa.Column("provider_metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_profile_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["artist_profile_id"],
            ["artist_profiles.id"],
            name=op.f(
                "fk_social_account_connections_artist_profile_id_artist_profiles"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_profile_id"],
            ["universal_profiles.id"],
            name=op.f(
                "fk_social_account_connections_created_by_profile_id_universal_profiles"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_social_account_connections_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_social_account_connections_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_social_account_connections")),
    )
    op.create_index(
        "ix_social_account_connections_organization_id",
        "social_account_connections",
        ["organization_id"],
    )
    op.create_index(
        "ix_social_account_connections_organization_provider",
        "social_account_connections",
        ["organization_id", "provider"],
    )
    op.create_index(
        "ix_social_account_connections_organization_status",
        "social_account_connections",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_social_account_connections_organization_artist_profile",
        "social_account_connections",
        ["organization_id", "artist_profile_id"],
    )
    op.create_index(
        "ix_social_account_connections_provider_external_account",
        "social_account_connections",
        ["provider", "external_account_id"],
    )
    op.create_index(
        "uq_social_account_connections_org_provider_external",
        "social_account_connections",
        ["organization_id", "provider", "external_account_id"],
        unique=True,
        postgresql_where=sa.text(
            "external_account_id IS NOT NULL AND status != 'disconnected'"
        ),
        sqlite_where=sa.text(
            "external_account_id IS NOT NULL AND status != 'disconnected'"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_social_account_connections_org_provider_external",
        table_name="social_account_connections",
    )
    op.drop_index(
        "ix_social_account_connections_provider_external_account",
        table_name="social_account_connections",
    )
    op.drop_index(
        "ix_social_account_connections_organization_artist_profile",
        table_name="social_account_connections",
    )
    op.drop_index(
        "ix_social_account_connections_organization_status",
        table_name="social_account_connections",
    )
    op.drop_index(
        "ix_social_account_connections_organization_provider",
        table_name="social_account_connections",
    )
    op.drop_index(
        "ix_social_account_connections_organization_id",
        table_name="social_account_connections",
    )
    op.drop_table("social_account_connections")

    bind = op.get_bind()
    social_account_connection_status.drop(bind, checkfirst=True)
    social_account_connection_method.drop(bind, checkfirst=True)
