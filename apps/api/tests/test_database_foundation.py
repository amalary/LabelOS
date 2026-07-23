from labelos_database.config import DatabaseSettings
from labelos_database.models import (
    AIAgent,
    AnalyticsEvent,
    Artist,
    AuthIdentity,
    Campaign,
    Contract,
    MembershipRole,
    Organization,
    OrganizationMembership,
    Release,
    Royalty,
    TeamSetting,
    User,
    WebhookEvent,
)


def test_database_url_accepts_standard_postgres_scheme() -> None:
    settings = DatabaseSettings(
        database_url="postgresql://labelos:password@localhost:5432/labelos"
    )

    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_foundational_models_are_registered() -> None:
    tables = {
        User.__tablename__,
        AuthIdentity.__tablename__,
        Organization.__tablename__,
        OrganizationMembership.__tablename__,
        Artist.__tablename__,
        Release.__tablename__,
        Campaign.__tablename__,
        Contract.__tablename__,
        Royalty.__tablename__,
        AnalyticsEvent.__tablename__,
        AIAgent.__tablename__,
        TeamSetting.__tablename__,
        WebhookEvent.__tablename__,
    }

    assert tables == {
        "users",
        "auth_identities",
        "organizations",
        "organization_memberships",
        "artists",
        "releases",
        "campaigns",
        "contracts",
        "royalties",
        "analytics_events",
        "ai_agents",
        "team_settings",
        "webhook_events",
    }


def test_memberships_define_organization_boundary_constraints() -> None:
    organization_constraint_names = {
        constraint.name for constraint in Organization.__table__.constraints
    }
    table = OrganizationMembership.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "uq_organizations_workos_organization_id" in organization_constraint_names
    assert "uq_organization_memberships_organization_id_user_id" in constraint_names
    assert "ix_organization_memberships_organization_id" in index_names
    assert "ix_organization_memberships_user_id" in index_names
    assert MembershipRole.owner.value == "owner"
    assert MembershipRole.viewer.value == "viewer"


def test_users_define_workos_identity_without_email_identity_constraint() -> None:
    table = User.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "workos_user_id" in table.columns
    assert "first_name" in table.columns
    assert "last_name" in table.columns
    assert "profile_image_url" in table.columns
    assert "uq_users_workos_user_id" in constraint_names
    assert "ix_users_workos_user_id" in index_names
    assert "uq_users_email" not in constraint_names
    assert not table.c.email.primary_key


def test_organizations_define_workos_external_identifier_index() -> None:
    table = Organization.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "workos_organization_id" in table.columns
    assert "uq_organizations_workos_organization_id" in constraint_names
    assert "ix_organizations_workos_organization_id" in index_names
    assert not table.c.workos_organization_id.primary_key


def test_memberships_define_workos_identity_status_and_foreign_keys() -> None:
    table = OrganizationMembership.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert "workos_membership_id" in table.columns
    assert "status" in table.columns
    assert "uq_organization_memberships_workos_membership_id" in constraint_names
    assert "ix_organization_memberships_workos_membership_id" in index_names
    assert foreign_key_deletions == {
        "organization_id": "CASCADE",
        "user_id": "CASCADE",
    }
    assert table.c.status.server_default is not None


def test_webhook_events_define_idempotency_and_ordering_indexes() -> None:
    table = WebhookEvent.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "event_id" in table.columns
    assert "event_type" in table.columns
    assert "resource_type" in table.columns
    assert "resource_id" in table.columns
    assert "workos_event_created_at" in table.columns
    assert "processing_status" in table.columns
    assert "uq_webhook_events_provider_id" in constraint_names
    assert "ix_webhook_events_provider_event_id" in index_names
    assert "ix_webhook_events_resource_created_at" in index_names


def test_label_owned_resources_define_organization_boundary() -> None:
    models = (
        Artist,
        Release,
        Campaign,
        Contract,
        Royalty,
        AnalyticsEvent,
        AIAgent,
        TeamSetting,
    )

    for model in models:
        table = model.__table__
        index_names = {index.name for index in table.indexes}
        foreign_key_deletions = {
            foreign_key.parent.name: foreign_key.ondelete
            for foreign_key in table.foreign_keys
        }

        assert "organization_id" in table.columns
        assert foreign_key_deletions["organization_id"] == "CASCADE"
        assert f"ix_{table.name}_organization_id" in index_names


def test_label_owned_unique_constraints_are_organization_scoped() -> None:
    artist_constraints = {
        constraint.name for constraint in Artist.__table__.constraints
    }
    agent_constraints = {
        constraint.name for constraint in AIAgent.__table__.constraints
    }
    setting_constraints = {
        constraint.name for constraint in TeamSetting.__table__.constraints
    }

    assert "uq_artists_organization_id_name" in artist_constraints
    assert "uq_ai_agents_organization_id_name" in agent_constraints
    assert "uq_team_settings_organization_id_key" in setting_constraints
