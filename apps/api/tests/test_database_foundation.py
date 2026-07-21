from labelos_database.config import DatabaseSettings
from labelos_database.models import (
    AuthIdentity,
    MembershipRole,
    Organization,
    OrganizationMembership,
    User,
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
    }

    assert tables == {
        "users",
        "auth_identities",
        "organizations",
        "organization_memberships",
    }


def test_memberships_define_organization_boundary_constraints() -> None:
    table = OrganizationMembership.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "uq_organization_memberships_organization_id_user_id" in constraint_names
    assert "ix_organization_memberships_organization_id" in index_names
    assert "ix_organization_memberships_user_id" in index_names
    assert MembershipRole.owner.value == "owner"
    assert MembershipRole.viewer.value == "viewer"
