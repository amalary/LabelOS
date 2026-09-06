"""oauth authorization states

Revision ID: 202609061300
Revises: 202609051900
Create Date: 2026-09-06 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609061300"
down_revision: str | None = "202609051900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


social_account_connection_method = postgresql.ENUM(
    "direct_api",
    "third_party",
    "assisted",
    name="social_account_connection_method",
    create_type=False,
)

oauth_authorization_state_status = postgresql.ENUM(
    "pending",
    "consumed",
    "expired",
    name="oauth_authorization_state_status",
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
    oauth_authorization_state_status.create(bind, checkfirst=True)

    op.create_table(
        "oauth_authorization_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column(
            "connection_method",
            social_account_connection_method,
            nullable=False,
        ),
        sa.Column(
            "status",
            oauth_authorization_state_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_redirect_path", sa.String(length=2048), nullable=False),
        sa.Column("pkce_credential_ref", sa.String(length=500), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_oauth_authorization_states_actor_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_oauth_authorization_states_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_authorization_states")),
        sa.UniqueConstraint(
            "state_hash",
            name="uq_oauth_authorization_states_hash",
        ),
    )
    op.create_index(
        "ix_oauth_authorization_states_organization_id",
        "oauth_authorization_states",
        ["organization_id"],
    )
    op.create_index(
        "ix_oauth_authorization_states_org_provider_method",
        "oauth_authorization_states",
        ["organization_id", "provider", "connection_method"],
    )
    op.create_index(
        "ix_oauth_authorization_states_actor_user_id",
        "oauth_authorization_states",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_oauth_authorization_states_status_expires_at",
        "oauth_authorization_states",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_oauth_authorization_states_status_expires_at",
        table_name="oauth_authorization_states",
    )
    op.drop_index(
        "ix_oauth_authorization_states_actor_user_id",
        table_name="oauth_authorization_states",
    )
    op.drop_index(
        "ix_oauth_authorization_states_org_provider_method",
        table_name="oauth_authorization_states",
    )
    op.drop_index(
        "ix_oauth_authorization_states_organization_id",
        table_name="oauth_authorization_states",
    )
    op.drop_table("oauth_authorization_states")

    bind = op.get_bind()
    oauth_authorization_state_status.drop(bind, checkfirst=True)
