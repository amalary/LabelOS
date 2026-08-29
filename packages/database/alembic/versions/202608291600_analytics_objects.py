"""analytics objects

Revision ID: 202608291600
Revises: 202608271400
Create Date: 2026-08-29 16:00:00.000000

"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "202608291600"
down_revision: str | None = "202608271400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ANALYTICS_CREATE_ID = uuid5(
    NAMESPACE_URL,
    "labelos-capability:analytics.create",
)


def upgrade() -> None:
    op.create_table(
        "analytics_providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column(
            "provider_type",
            sa.String(length=80),
            server_default="internal",
            nullable=False,
        ),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
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
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_analytics_providers_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analytics_providers")),
        sa.UniqueConstraint(
            "organization_id",
            "key",
            name="uq_analytics_providers_organization_id_key",
        ),
    )
    op.create_index(
        "ix_analytics_providers_organization_id",
        "analytics_providers",
        ["organization_id"],
    )
    op.create_index(
        "ix_analytics_providers_organization_id_provider_type",
        "analytics_providers",
        ["organization_id", "provider_type"],
    )

    op.create_table(
        "analytics_metric_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column(
            "value_type",
            sa.Enum(
                "integer",
                "decimal",
                "string",
                "boolean",
                "json",
                name="analytics_metric_value_type",
            ),
            server_default="decimal",
            nullable=False,
        ),
        sa.Column("default_unit", sa.String(length=80), nullable=True),
        sa.Column("aggregation", sa.String(length=80), nullable=True),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
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
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_analytics_metric_definitions_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["analytics_providers.id"],
            name=op.f(
                "fk_analytics_metric_definitions_provider_id_analytics_providers"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_analytics_metric_definitions"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "provider_id",
            "key",
            name="uq_analytics_metric_definitions_workspace_provider_key",
        ),
    )
    op.create_index(
        "ix_analytics_metric_definitions_organization_id",
        "analytics_metric_definitions",
        ["organization_id"],
    )
    op.create_index(
        "ix_analytics_metric_definitions_provider_id",
        "analytics_metric_definitions",
        ["provider_id"],
    )
    op.create_index(
        "ix_analytics_metric_definitions_workspace_key",
        "analytics_metric_definitions",
        ["organization_id", "key"],
    )
    op.create_index(
        "ix_analytics_metric_definitions_workspace_value_type",
        "analytics_metric_definitions",
        ["organization_id", "value_type"],
    )

    op.create_table(
        "analytics_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("metric_definition_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("artist_profile_id", sa.Uuid(), nullable=True),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("campaign_object_type", sa.String(length=120), nullable=True),
        sa.Column("campaign_object_id", sa.Uuid(), nullable=True),
        sa.Column("value_numeric", sa.Numeric(24, 6), nullable=True),
        sa.Column("value_text", sa.String(length=1000), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(length=80), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("dimensions", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
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
        sa.ForeignKeyConstraint(
            ["artist_profile_id"],
            ["artist_profiles.id"],
            name=op.f("fk_analytics_observations_artist_profile_id_artist_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_analytics_observations_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["metric_definition_id"],
            ["analytics_metric_definitions.id"],
            name=op.f(
                "fk_analytics_observations_metric_definition_id_analytics_metric_definitions"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_analytics_observations_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["analytics_providers.id"],
            name=op.f("fk_analytics_observations_provider_id_analytics_providers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analytics_observations")),
        sa.UniqueConstraint(
            "organization_id",
            "provider_id",
            "idempotency_key",
            name="uq_analytics_observations_workspace_provider_idempotency",
        ),
    )
    op.create_index(
        "ix_analytics_observations_organization_id",
        "analytics_observations",
        ["organization_id"],
    )
    op.create_index(
        "ix_analytics_observations_metric_definition_id",
        "analytics_observations",
        ["metric_definition_id"],
    )
    op.create_index(
        "ix_analytics_observations_provider_id",
        "analytics_observations",
        ["provider_id"],
    )
    op.create_index(
        "ix_analytics_observations_workspace_metric_observed",
        "analytics_observations",
        ["organization_id", "metric_definition_id", "observed_at"],
    )
    op.create_index(
        "ix_analytics_observations_workspace_target_observed",
        "analytics_observations",
        ["organization_id", "target_type", "target_id", "observed_at"],
    )
    op.create_index(
        "ix_analytics_observations_workspace_artist_observed",
        "analytics_observations",
        ["organization_id", "artist_profile_id", "observed_at"],
    )
    op.create_index(
        "ix_analytics_observations_workspace_campaign_observed",
        "analytics_observations",
        ["organization_id", "campaign_id", "observed_at"],
    )
    op.create_index(
        "ix_analytics_observations_workspace_campaign_object_observed",
        "analytics_observations",
        [
            "organization_id",
            "campaign_object_type",
            "campaign_object_id",
            "observed_at",
        ],
    )
    op.create_index(
        "ix_analytics_observations_workspace_source_record",
        "analytics_observations",
        ["organization_id", "provider_id", "source_record_id"],
    )
    _seed_analytics_create_capability()


def _seed_analytics_create_capability() -> None:
    bind = op.get_bind()
    capability_id = bind.execute(
        sa.text("SELECT id FROM capabilities WHERE key = 'analytics.create'")
    ).scalar_one_or_none()
    if capability_id is None:
        capability_id = ANALYTICS_CREATE_ID
        bind.execute(
            sa.text("""
                INSERT INTO capabilities (
                    id,
                    key,
                    display_name,
                    description,
                    system_capability
                )
                VALUES (
                    :id,
                    'analytics.create',
                    'Create analytics',
                    'Create analytics metric definitions and observations.',
                    TRUE
                )
            """),
            {"id": capability_id},
        )

    role_rows = bind.execute(sa.text("""
            SELECT id, key
            FROM roles
            WHERE workspace_id IS NULL
                AND is_system_role IS TRUE
                AND key IN ('admin', 'marketing')
        """))
    for role_id, role_key in role_rows:
        existing_id = bind.execute(
            sa.text("""
                SELECT id
                FROM role_capabilities
                WHERE role_id = :role_id
                    AND capability_id = :capability_id
            """),
            {"role_id": role_id, "capability_id": capability_id},
        ).scalar_one_or_none()
        if existing_id is not None:
            continue
        bind.execute(
            sa.text("""
                INSERT INTO role_capabilities (
                    id,
                    role_id,
                    capability_id,
                    source
                )
                VALUES (
                    :id,
                    :role_id,
                    :capability_id,
                    'system_default'
                )
            """),
            {
                "id": uuid5(
                    NAMESPACE_URL,
                    f"labelos-role-capability:{role_key}:analytics.create",
                ),
                "role_id": role_id,
                "capability_id": capability_id,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    capability_id = bind.execute(
        sa.text("SELECT id FROM capabilities WHERE key = 'analytics.create'")
    ).scalar_one_or_none()
    if capability_id is not None:
        bind.execute(
            sa.text("""
                DELETE FROM role_capabilities
                WHERE capability_id = :capability_id
                    AND source = 'system_default'
            """),
            {"capability_id": capability_id},
        )
        bind.execute(
            sa.text("""
                DELETE FROM capabilities
                WHERE id = :capability_id
                    AND key = 'analytics.create'
                    AND system_capability IS TRUE
            """),
            {"capability_id": capability_id},
        )

    op.drop_index(
        "ix_analytics_observations_workspace_source_record",
        table_name="analytics_observations",
    )
    op.drop_index(
        "ix_analytics_observations_workspace_campaign_object_observed",
        table_name="analytics_observations",
    )
    op.drop_index(
        "ix_analytics_observations_workspace_campaign_observed",
        table_name="analytics_observations",
    )
    op.drop_index(
        "ix_analytics_observations_workspace_artist_observed",
        table_name="analytics_observations",
    )
    op.drop_index(
        "ix_analytics_observations_workspace_target_observed",
        table_name="analytics_observations",
    )
    op.drop_index(
        "ix_analytics_observations_workspace_metric_observed",
        table_name="analytics_observations",
    )
    op.drop_index(
        "ix_analytics_observations_provider_id",
        table_name="analytics_observations",
    )
    op.drop_index(
        "ix_analytics_observations_metric_definition_id",
        table_name="analytics_observations",
    )
    op.drop_index(
        "ix_analytics_observations_organization_id",
        table_name="analytics_observations",
    )
    op.drop_table("analytics_observations")
    op.drop_index(
        "ix_analytics_metric_definitions_workspace_value_type",
        table_name="analytics_metric_definitions",
    )
    op.drop_index(
        "ix_analytics_metric_definitions_workspace_key",
        table_name="analytics_metric_definitions",
    )
    op.drop_index(
        "ix_analytics_metric_definitions_provider_id",
        table_name="analytics_metric_definitions",
    )
    op.drop_index(
        "ix_analytics_metric_definitions_organization_id",
        table_name="analytics_metric_definitions",
    )
    op.drop_table("analytics_metric_definitions")
    op.drop_index(
        "ix_analytics_providers_organization_id_provider_type",
        table_name="analytics_providers",
    )
    op.drop_index(
        "ix_analytics_providers_organization_id",
        table_name="analytics_providers",
    )
    op.drop_table("analytics_providers")
