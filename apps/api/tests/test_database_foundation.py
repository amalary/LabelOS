from pathlib import Path

import pytest
from labelos_database.config import DatabaseSettings
from labelos_database.departments import (
    DEFAULT_DEPARTMENTS,
    DEFAULT_ROLE_DEPARTMENT_ACCESS,
    DEFAULT_ROLE_DEPARTMENT_ASSOCIATIONS,
    ELEVATED_DEPARTMENT_SLUGS,
    SENSITIVE_DEPARTMENT_SLUGS,
    STANDARD_DEPARTMENT_SLUGS,
    DepartmentAccessSensitivity,
    department_access_sensitivity_for_slug,
)
from labelos_database.models import (
    AIAgent,
    AnalyticsEvent,
    Artist,
    ArtistProfile,
    AuthIdentity,
    Campaign,
    Contract,
    Department,
    MembershipDepartmentAccess,
    MembershipProfessionalRole,
    MembershipRole,
    Organization,
    OrganizationMembership,
    ProfessionalRole,
    ProfileAttribute,
    ProfileLink,
    ProfilePreference,
    Release,
    Role,
    RoleCapability,
    RoleDepartment,
    Royalty,
    TeamSetting,
    UniversalProfile,
    User,
    WebhookEvent,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspacePermission,
)
from labelos_database.models import (
    Capability as CapabilityModel,
)
from labelos_database.roles import (
    DEFAULT_CAPABILITIES,
    DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS,
    DEFAULT_ROLES,
)
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[3]


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
        MembershipProfessionalRole.__tablename__,
        MembershipDepartmentAccess.__tablename__,
        ProfessionalRole.__tablename__,
        Department.__tablename__,
        Artist.__tablename__,
        ArtistProfile.__tablename__,
        Release.__tablename__,
        Campaign.__tablename__,
        Contract.__tablename__,
        Royalty.__tablename__,
        AnalyticsEvent.__tablename__,
        AIAgent.__tablename__,
        TeamSetting.__tablename__,
        WebhookEvent.__tablename__,
        UniversalProfile.__tablename__,
        ProfileAttribute.__tablename__,
        ProfileLink.__tablename__,
        ProfilePreference.__tablename__,
        WorkspaceMembership.__tablename__,
        Role.__tablename__,
        CapabilityModel.__tablename__,
        RoleCapability.__tablename__,
        RoleDepartment.__tablename__,
        WorkspaceMembershipRole.__tablename__,
    }

    assert tables == {
        "users",
        "auth_identities",
        "organizations",
        "organization_memberships",
        "membership_professional_roles",
        "membership_department_access",
        "professional_roles",
        "departments",
        "artists",
        "artist_profiles",
        "releases",
        "campaigns",
        "contracts",
        "royalties",
        "analytics_events",
        "ai_agents",
        "team_settings",
        "webhook_events",
        "universal_profiles",
        "profile_attributes",
        "profile_links",
        "profile_preferences",
        "workspace_memberships",
        "roles",
        "capabilities",
        "role_capabilities",
        "role_departments",
        "workspace_membership_roles",
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
    assert MembershipRole.guest.value == "guest"
    assert WorkspacePermission.guest.value == "guest"


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
    assert User.universal_profile.property.uselist is False


def test_universal_profiles_define_user_profile_contract() -> None:
    table = UniversalProfile.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert "id" in table.columns
    assert "user_id" in table.columns
    assert "display_name" in table.columns
    assert "first_name" in table.columns
    assert "last_name" in table.columns
    assert "slug" in table.columns
    assert "headline" in table.columns
    assert "biography" in table.columns
    assert "avatar_url" in table.columns
    assert "location" in table.columns
    assert "timezone" in table.columns
    assert "primary_email" in table.columns
    assert "profile_status" in table.columns
    assert "onboarding_status" in table.columns
    assert "created_at" in table.columns
    assert "updated_at" in table.columns
    assert table.c.id.primary_key
    assert table.c.user_id.nullable is False
    assert table.c.profile_status.server_default is not None
    assert table.c.onboarding_status.server_default is not None
    assert "uq_universal_profiles_user_id" in constraint_names
    assert "uq_universal_profiles_slug" in constraint_names
    assert "ix_universal_profiles_user_id" in index_names
    assert "ix_universal_profiles_slug" in index_names
    assert "ix_universal_profiles_display_name" in index_names
    assert "ix_universal_profiles_primary_email" in index_names
    assert "ix_universal_profiles_profile_status" in index_names
    assert "ix_universal_profiles_onboarding_status" in index_names
    assert foreign_key_deletions == {"user_id": "CASCADE"}
    assert UniversalProfile.user.property.uselist is False
    assert UniversalProfile.attributes.property.uselist is True
    assert UniversalProfile.links.property.uselist is True
    assert UniversalProfile.preference.property.uselist is False
    assert UniversalProfile.artist_profiles.property.uselist is True


def test_artist_profiles_define_domain_extension_contract() -> None:
    table = ArtistProfile.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert "artist_id" in table.columns
    assert "universal_profile_id" in table.columns
    assert "stage_name" in table.columns
    assert "genres" in table.columns
    assert "influences" in table.columns
    assert "biography" not in table.columns
    assert "imagery" in table.columns
    assert "dsp_links" in table.columns
    assert "catalog_references" in table.columns
    assert "creative_metadata" in table.columns
    assert "career_stage" in table.columns
    assert "audience" in table.columns
    assert "preferences" in table.columns
    assert "uq_artist_profiles_artist_id" in constraint_names
    assert "ix_artist_profiles_artist_id" in index_names
    assert "ix_artist_profiles_universal_profile_id" in index_names
    assert "ix_artist_profiles_stage_name" in index_names
    assert "ix_artist_profiles_career_stage" in index_names
    assert table.c.universal_profile_id.nullable is False
    assert foreign_key_deletions == {
        "artist_id": "CASCADE",
        "universal_profile_id": "CASCADE",
    }
    assert table.c.genres.server_default is not None
    assert table.c.imagery.server_default is not None
    assert Artist.profile.property.uselist is False
    assert ArtistProfile.artist.property.uselist is False
    assert ArtistProfile.universal_profile.property.uselist is False


def test_artist_profile_migrations_do_not_delete_unlinked_catalog_data() -> None:
    artist_profile_migration = (
        REPO_ROOT / "packages/database/alembic/versions/202608250200_artist_profiles.py"
    ).read_text()
    module_architecture_migration = (
        REPO_ROOT
        / "packages/database/alembic/versions"
        / "202608250300_profile_module_architecture.py"
    ).read_text()

    assert "SELECT id, name FROM artists" not in artist_profile_migration
    assert "DELETE FROM artist_profiles" not in module_architecture_migration
    assert "universal_profile_id IS NULL" in module_architecture_migration
    assert "Cannot make artist_profiles.universal_profile_id non-null" in (
        module_architecture_migration
    )
    assert "SET biography = (" in (module_architecture_migration)


def test_profile_attributes_define_extensible_profile_metadata() -> None:
    table = ProfileAttribute.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert "profile_id" in table.columns
    assert "attribute_type" in table.columns
    assert "label" in table.columns
    assert "value" in table.columns
    assert "source" in table.columns
    assert "is_primary" in table.columns
    assert "sort_order" in table.columns
    assert "metadata" in table.columns
    assert "uq_profile_attributes_profile_id_type_value" in constraint_names
    assert "ix_profile_attributes_profile_id" in index_names
    assert "ix_profile_attributes_attribute_type" in index_names
    assert "ix_profile_attributes_profile_id_type" in index_names
    assert foreign_key_deletions == {"profile_id": "CASCADE"}
    assert table.c.source.server_default is not None
    assert table.c.is_primary.server_default is not None
    assert table.c.metadata.server_default is not None
    assert ProfileAttribute.profile.property.uselist is False


def test_profile_links_define_structured_external_links() -> None:
    table = ProfileLink.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert "profile_id" in table.columns
    assert "link_type" in table.columns
    assert "label" in table.columns
    assert "url" in table.columns
    assert "username" in table.columns
    assert "external_id" in table.columns
    assert "status" in table.columns
    assert "is_primary" in table.columns
    assert "sort_order" in table.columns
    assert "metadata" in table.columns
    assert "uq_profile_links_profile_id_type_url" in constraint_names
    assert "ix_profile_links_profile_id" in index_names
    assert "ix_profile_links_link_type" in index_names
    assert "ix_profile_links_profile_id_type" in index_names
    assert "ix_profile_links_status" in index_names
    assert foreign_key_deletions == {"profile_id": "CASCADE"}
    assert table.c.status.server_default is not None
    assert table.c.metadata.server_default is not None
    assert ProfileLink.profile.property.uselist is False


def test_profile_preferences_define_structured_preference_contract() -> None:
    table = ProfilePreference.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert "profile_id" in table.columns
    assert "locale" in table.columns
    assert "timezone" in table.columns
    assert "default_workspace_id" in table.columns
    assert "email_notifications_enabled" in table.columns
    assert "push_notifications_enabled" in table.columns
    assert "sms_notifications_enabled" in table.columns
    assert "marketing_notifications_enabled" in table.columns
    assert "interface_theme" in table.columns
    assert "interface_density" in table.columns
    assert "notification_preferences" in table.columns
    assert "interface_preferences" in table.columns
    assert "integration_preferences" in table.columns
    assert "uq_profile_preferences_profile_id" in constraint_names
    assert "ix_profile_preferences_profile_id" in index_names
    assert "ix_profile_preferences_locale" in index_names
    assert "ix_profile_preferences_timezone" in index_names
    assert "ix_profile_preferences_default_workspace_id" in index_names
    assert foreign_key_deletions == {
        "profile_id": "CASCADE",
        "default_workspace_id": "SET NULL",
    }
    assert table.c.email_notifications_enabled.server_default is not None
    assert table.c.notification_preferences.server_default is not None
    assert ProfilePreference.profile.property.uselist is False


def test_workspace_memberships_define_profile_workspace_contract() -> None:
    table = WorkspaceMembership.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert "id" in table.columns
    assert "workspace_id" in table.columns
    assert "profile_id" in table.columns
    assert "organization_membership_id" in table.columns
    assert "status" in table.columns
    assert "invited_by" in table.columns
    assert "joined_at" in table.columns
    assert "created_at" in table.columns
    assert "updated_at" in table.columns
    assert "user_id" not in table.columns
    assert "uq_workspace_memberships_workspace_id_profile_id" in constraint_names
    assert "uq_workspace_memberships_organization_membership_id" in constraint_names
    assert "ix_workspace_memberships_workspace_id" in index_names
    assert "ix_workspace_memberships_profile_id" in index_names
    assert "ix_workspace_memberships_status" in index_names
    assert foreign_key_deletions == {
        "workspace_id": "CASCADE",
        "profile_id": "CASCADE",
        "organization_membership_id": "SET NULL",
        "invited_by": "SET NULL",
    }
    assert table.c.status.server_default is not None
    assert WorkspaceMembership.profile.property.uselist is False
    assert WorkspaceMembership.workspace.property.uselist is False
    assert WorkspaceMembership.organization_membership.property.uselist is False
    assert WorkspaceMembership.role_assignments.property.uselist is True


def test_roles_define_extensible_workspace_role_registry() -> None:
    table = Role.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "id" in table.columns
    assert "key" in table.columns
    assert "display_name" in table.columns
    assert "description" in table.columns
    assert "system_role" in table.columns
    assert "created_at" in table.columns
    assert "updated_at" in table.columns
    assert table.c.id.primary_key
    assert table.c.system_role.server_default is not None
    assert "uq_roles_key" in constraint_names
    assert "ix_roles_key" in index_names
    assert "ix_roles_system_role" in index_names
    assert Role.workspace_membership_assignments.property.uselist is True
    assert Role.capability_links.property.uselist is True


def test_default_roles_match_initial_system_catalog() -> None:
    roles_by_key = {role.key: role for role in DEFAULT_ROLES}

    assert tuple(roles_by_key) == (
        "artist",
        "manager",
        "producer",
        "songwriter",
        "a&r",
        "marketing",
        "release_operations",
        "legal",
        "finance",
        "analytics",
        "executive",
        "administrator",
    )
    assert all(role.system_role for role in DEFAULT_ROLES)
    assert roles_by_key["release_operations"].display_name == "Release Operations"


def test_capabilities_define_action_catalog() -> None:
    table = CapabilityModel.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "id" in table.columns
    assert "key" in table.columns
    assert "display_name" in table.columns
    assert "description" in table.columns
    assert "system_capability" in table.columns
    assert "created_at" in table.columns
    assert "updated_at" in table.columns
    assert table.c.id.primary_key
    assert table.c.system_capability.server_default is not None
    assert "uq_capabilities_key" in constraint_names
    assert "ix_capabilities_key" in index_names
    assert "ix_capabilities_system_capability" in index_names
    assert CapabilityModel.role_links.property.uselist is True


def test_default_capabilities_are_specific_actions() -> None:
    capability_keys = {capability.key for capability in DEFAULT_CAPABILITIES}

    assert {
        "artist.view",
        "artist.edit",
        "artist.create",
        "campaign.view",
        "campaign.create",
        "campaign.approve",
        "release.view",
        "release.edit",
        "contract.view",
        "contract.upload",
        "contract.approve",
        "contract.sign_request",
        "royalty.view",
        "finance.view",
        "analytics.view",
        "member.invite",
        "member.remove",
        "role.assign",
        "workspace.manage",
        "profile.edit",
    } <= capability_keys
    assert all(capability.system_capability for capability in DEFAULT_CAPABILITIES)
    assert all("." in capability.key for capability in DEFAULT_CAPABILITIES)
    capability_actions = {
        capability.key.split(".")[-1]
        for capability in DEFAULT_CAPABILITIES
        if capability.key != "workspace.manage"
    }
    assert "manage" not in capability_actions


def test_default_role_capability_mapping_references_configured_registries() -> None:
    role_keys = {role.key for role in DEFAULT_ROLES}
    capability_keys = {capability.key for capability in DEFAULT_CAPABILITIES}

    assert DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS["legal"] == (
        "contract.view",
        "contract.upload",
        "contract.approve",
        "contract.sign_request",
        "profile.edit",
    )
    assert "workspace.manage" in DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS["administrator"]
    assert set(DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS) <= role_keys
    assert {
        capability_key
        for capability_keys_for_role in DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS.values()
        for capability_key in capability_keys_for_role
    } <= capability_keys


def test_workspace_membership_roles_define_many_to_many_assignment() -> None:
    table = WorkspaceMembershipRole.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert "id" in table.columns
    assert "membership_id" in table.columns
    assert "role_id" in table.columns
    assert "assigned_by" in table.columns
    assert "assigned_at" in table.columns
    assert "metadata" in table.columns
    assert "created_at" in table.columns
    assert "pk_workspace_membership_roles" in constraint_names
    assert "uq_workspace_membership_roles_membership_id_role_id" in constraint_names
    assert "ix_workspace_membership_roles_membership_id" in index_names
    assert "ix_workspace_membership_roles_role_id" in index_names
    assert "ix_workspace_membership_roles_assigned_by" in index_names
    assert "ix_workspace_membership_roles_assigned_at" in index_names
    assert foreign_key_deletions == {
        "membership_id": "CASCADE",
        "role_id": "CASCADE",
        "assigned_by": "SET NULL",
    }
    assert WorkspaceMembershipRole.workspace_membership.property.uselist is False
    assert WorkspaceMembershipRole.role.property.uselist is False


def test_role_capabilities_define_many_to_many_assignment() -> None:
    table = RoleCapability.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert "id" in table.columns
    assert "role_id" in table.columns
    assert "capability_id" in table.columns
    assert "source" in table.columns
    assert "created_at" in table.columns
    assert "pk_role_capabilities" in constraint_names
    assert "uq_role_capabilities_role_id_capability_id" in constraint_names
    assert "ix_role_capabilities_role_id" in index_names
    assert "ix_role_capabilities_capability_id" in index_names
    assert "ix_role_capabilities_source" in index_names
    assert foreign_key_deletions == {
        "role_id": "CASCADE",
        "capability_id": "CASCADE",
    }
    assert table.c.source.server_default is not None
    assert RoleCapability.role.property.uselist is False
    assert RoleCapability.capability.property.uselist is False


def test_workspace_membership_derives_capabilities_from_assigned_roles() -> None:
    engine = create_engine("sqlite:///:memory:")
    RoleCapability.metadata.create_all(engine)

    with Session(engine) as session:
        workspace = Organization(
            name="Example Label",
            slug="example-label",
            owner=User(email="owner@example.com"),
        )
        profile = UniversalProfile(
            user=User(email="member@example.com"),
            slug="member-profile",
        )
        role = Role(
            key="legal",
            display_name="Legal",
            description="Legal role.",
        )
        capability = CapabilityModel(
            key="contract.approve",
            display_name="Approve contracts",
            description="Approve contracts.",
        )
        membership = WorkspaceMembership(workspace=workspace, profile=profile)
        membership.role_assignments.append(WorkspaceMembershipRole(role=role))
        role.capability_links.append(RoleCapability(capability=capability))
        session.add(membership)
        session.commit()
        session.refresh(membership)

        assert membership.role_keys == ("legal",)
        assert membership.capability_keys == ("contract.approve",)
    engine.dispose()


def test_universal_profile_creation_and_relationship() -> None:
    engine = create_engine("sqlite:///:memory:")
    UniversalProfile.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(email="profile@example.com", workos_user_id="user_profile")
        profile = UniversalProfile(
            user=user,
            display_name="Profile Owner",
            slug="profile-owner",
            headline="Label operator",
            primary_email="contact@example.com",
        )
        session.add(profile)
        session.commit()
        session.refresh(user)

        assert profile.id is not None
        assert user.universal_profile == profile
        assert profile.user == user
        assert profile.profile_status == "active"
        assert profile.onboarding_status == "not_started"
    engine.dispose()


def test_artist_profile_extends_universal_profile_without_replacing_artist() -> None:
    engine = create_engine("sqlite:///:memory:")
    ArtistProfile.metadata.create_all(engine)

    with Session(engine) as session:
        owner = User(email="owner@example.com")
        universal_profile = UniversalProfile(
            user=User(email="artist@example.com"),
            display_name="Legal Name",
            slug="artist-legal-profile",
            primary_email="artist@example.com",
        )
        organization = Organization(
            name="Example Label",
            slug="example-label",
            owner=owner,
        )
        artist = Artist(name="Legacy Artist Name", organization=organization)
        artist_profile = ArtistProfile(
            artist=artist,
            universal_profile=universal_profile,
            stage_name="Stage Name",
            genres=["pop", "dance"],
            influences=["classic disco"],
            imagery={"avatar": "https://cdn.example.com/artist.jpg"},
            dsp_links={"spotify": "https://open.spotify.com/artist/example"},
            catalog_references=["cat-001"],
            creative_metadata={"mood": "bright"},
            career_stage="emerging",
            audience={"markets": ["US"]},
            preferences={"release_cadence": "monthly"},
        )
        session.add(artist_profile)
        session.commit()
        session.refresh(artist)
        session.refresh(universal_profile)

        assert artist.name == "Legacy Artist Name"
        assert artist.profile == artist_profile
        assert artist.profile.stage_name == "Stage Name"
        assert artist.profile.genres == ["pop", "dance"]
        assert universal_profile.display_name == "Legal Name"
        assert universal_profile.artist_profiles == [artist_profile]
        assert universal_profile.profile_modules == {"artist": [artist_profile]}
    engine.dispose()


def test_universal_profiles_enforce_one_profile_per_user() -> None:
    engine = create_engine("sqlite:///:memory:")
    UniversalProfile.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(email="single-profile@example.com", workos_user_id="user_single")
        session.add_all(
            [
                UniversalProfile(user=user, slug="single-profile"),
                UniversalProfile(user=user, slug="single-profile-two"),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()


def test_universal_profiles_enforce_unique_slug() -> None:
    engine = create_engine("sqlite:///:memory:")
    UniversalProfile.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                UniversalProfile(
                    user=User(email="slug-one@example.com", workos_user_id="user_one"),
                    slug="shared-profile",
                ),
                UniversalProfile(
                    user=User(email="slug-two@example.com", workos_user_id="user_two"),
                    slug="shared-profile",
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()


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
    assert "workspace_permission" in table.columns
    assert "department_access" in table.columns
    assert "status" in table.columns
    assert "uq_organization_memberships_workos_membership_id" in constraint_names
    assert "ix_organization_memberships_workos_membership_id" in index_names
    assert foreign_key_deletions == {
        "organization_id": "CASCADE",
        "user_id": "CASCADE",
    }
    assert table.c.status.server_default is not None
    assert table.c.workspace_permission.server_default is not None
    assert table.c.department_access.server_default is not None


def test_professional_roles_define_controlled_registry() -> None:
    table = ProfessionalRole.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "id" in table.columns
    assert "slug" in table.columns
    assert "display_name" in table.columns
    assert "description" in table.columns
    assert "default_department_access" in table.columns
    assert "is_active" in table.columns
    assert table.c.id.primary_key
    assert "uq_professional_roles_slug" in constraint_names
    assert "ix_professional_roles_slug" in index_names
    assert "ix_professional_roles_is_active" in index_names
    assert table.c.is_active.server_default is not None
    assert table.c.default_department_access.server_default is not None


def test_departments_define_controlled_registry() -> None:
    table = Department.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "id" in table.columns
    assert "slug" in table.columns
    assert "display_name" in table.columns
    assert "description" in table.columns
    assert "access_sensitivity" in table.columns
    assert "is_active" in table.columns
    assert table.c.id.primary_key
    assert "uq_departments_slug" in constraint_names
    assert "ix_departments_slug" in index_names
    assert "ix_departments_is_active" in index_names
    assert table.c.access_sensitivity.server_default is not None
    assert table.c.is_active.server_default is not None
    department = Department(
        slug="creative",
        display_name="Creative",
        description="x",
    )
    assert department.key == "creative"


def test_default_departments_define_access_sensitivity_policies() -> None:
    departments_by_slug = {
        department.slug: department.access_sensitivity
        for department in DEFAULT_DEPARTMENTS
    }

    assert {
        "artist",
        "production",
        "creative",
        "marketing",
    } == STANDARD_DEPARTMENT_SLUGS
    assert {
        "management",
        "a&r",
        "analytics",
        "release_operations",
    } == ELEVATED_DEPARTMENT_SLUGS
    assert {
        "legal",
        "finance",
        "royalties",
        "administration",
    } == SENSITIVE_DEPARTMENT_SLUGS
    assert {
        slug
        for slug, sensitivity in departments_by_slug.items()
        if sensitivity == DepartmentAccessSensitivity.elevated
    } == ELEVATED_DEPARTMENT_SLUGS
    assert {
        slug
        for slug, sensitivity in departments_by_slug.items()
        if sensitivity == DepartmentAccessSensitivity.sensitive
    } == SENSITIVE_DEPARTMENT_SLUGS
    assert department_access_sensitivity_for_slug("unknown") == (
        DepartmentAccessSensitivity.standard
    )


def test_default_departments_include_major_operating_areas() -> None:
    departments_by_key = {
        department.key: department for department in DEFAULT_DEPARTMENTS
    }

    assert {
        "a&r",
        "management",
        "marketing",
        "release_operations",
        "legal",
        "finance",
        "royalties",
        "analytics",
        "creative",
        "administration",
    } <= set(departments_by_key)
    assert departments_by_key["management"].display_name == "Artist Management"
    assert departments_by_key["release_operations"].display_name == "Release Operations"


def test_default_role_department_mapping_references_configured_departments() -> None:
    department_slugs = {department.slug for department in DEFAULT_DEPARTMENTS}

    assert DEFAULT_ROLE_DEPARTMENT_ACCESS["artist"] == [
        "artist",
        "creative",
        "releases",
        "analytics",
    ]
    assert DEFAULT_ROLE_DEPARTMENT_ACCESS["producer"] == [
        "production",
        "songs",
        "sessions",
        "credits",
    ]
    assert DEFAULT_ROLE_DEPARTMENT_ACCESS["management"] == [
        "management",
        "artist",
        "releases",
        "marketing",
        "analytics",
    ]
    assert DEFAULT_ROLE_DEPARTMENT_ACCESS["a&r"] == [
        "a&r",
        "discovery",
        "artist",
        "evaluations",
    ]
    assert DEFAULT_ROLE_DEPARTMENT_ACCESS["legal"] == [
        "legal",
        "contracts",
        "agreements",
    ]
    assert DEFAULT_ROLE_DEPARTMENT_ACCESS["finance"] == [
        "finance",
        "royalties",
        "reporting",
    ]
    assert {
        department_slug
        for department_slugs in DEFAULT_ROLE_DEPARTMENT_ACCESS.values()
        for department_slug in department_slugs
    } <= department_slugs


def test_default_role_department_associations_reference_configured_registries() -> None:
    role_keys = {role.key for role in DEFAULT_ROLES}
    department_keys = {department.key for department in DEFAULT_DEPARTMENTS}

    assert DEFAULT_ROLE_DEPARTMENT_ASSOCIATIONS["a&r"] == ["a&r"]
    assert DEFAULT_ROLE_DEPARTMENT_ASSOCIATIONS["marketing"] == ["marketing"]
    assert DEFAULT_ROLE_DEPARTMENT_ASSOCIATIONS["artist"] == [
        "creative",
        "management",
    ]
    assert set(DEFAULT_ROLE_DEPARTMENT_ASSOCIATIONS) <= role_keys
    assert {
        department_key
        for department_keys in DEFAULT_ROLE_DEPARTMENT_ASSOCIATIONS.values()
        for department_key in department_keys
    } <= department_keys


def test_role_departments_define_many_to_many_responsibility_mapping() -> None:
    table = RoleDepartment.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert "id" in table.columns
    assert "role_id" in table.columns
    assert "department_id" in table.columns
    assert "access_level" in table.columns
    assert "source" in table.columns
    assert "created_at" in table.columns
    assert "pk_role_departments" in constraint_names
    assert "uq_role_departments_role_id_department_id" in constraint_names
    assert "ix_role_departments_role_id" in index_names
    assert "ix_role_departments_department_id" in index_names
    assert "ix_role_departments_access_level" in index_names
    assert "ix_role_departments_source" in index_names
    assert foreign_key_deletions == {
        "role_id": "CASCADE",
        "department_id": "CASCADE",
    }
    assert table.c.access_level.server_default is not None
    assert table.c.source.server_default is not None
    assert RoleDepartment.role.property.uselist is False
    assert RoleDepartment.department.property.uselist is False
    assert Role.department_links.property.uselist is True
    assert Department.role_links.property.uselist is True


def test_role_department_relationship_is_not_authorization() -> None:
    engine = create_engine("sqlite:///:memory:")
    RoleDepartment.metadata.create_all(engine)

    with Session(engine) as session:
        role = Role(
            key="marketing",
            display_name="Marketing Manager",
            description="Campaign owner.",
            system_role=True,
        )
        department = Department(
            slug="marketing",
            display_name="Marketing",
            description="Audience strategy and campaigns.",
        )
        link = RoleDepartment(role=role, department=department)
        session.add(link)
        session.commit()
        session.refresh(role)

        assert role.department_links[0].department.key == "marketing"
        assert role.department_links[0].access_level == "responsibility"
        assert "permission" not in RoleDepartment.__table__.columns
    engine.dispose()


def test_membership_professional_roles_define_many_to_many_assignment() -> None:
    table = MembershipProfessionalRole.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert "membership_id" in table.columns
    assert "professional_role_id" in table.columns
    assert "is_primary" in table.columns
    assert "status" in table.columns
    assert "created_at" in table.columns
    assert "pk_membership_professional_roles" in constraint_names
    assert "ix_membership_professional_roles_membership_id" in index_names
    assert "ix_membership_professional_roles_professional_role_id" in index_names
    assert "ix_membership_professional_roles_status" in index_names
    assert foreign_key_deletions == {
        "membership_id": "CASCADE",
        "professional_role_id": "CASCADE",
    }
    assert table.c.is_primary.server_default is not None
    assert table.c.status.server_default is not None


def test_membership_department_access_defines_grant_state() -> None:
    table = MembershipDepartmentAccess.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert "membership_id" in table.columns
    assert "department_id" in table.columns
    assert "access_level" in table.columns
    assert "source" in table.columns
    assert "approved_by" in table.columns
    assert "approved_at" in table.columns
    assert "created_at" in table.columns
    assert "updated_at" in table.columns
    assert "pk_membership_department_access" in constraint_names
    assert "uq_membership_department_access_membership_id_department_id" in (
        constraint_names
    )
    assert "ix_membership_department_access_membership_id" in index_names
    assert "ix_membership_department_access_department_id" in index_names
    assert "ix_membership_department_access_access_level" in index_names
    assert "ix_membership_department_access_source" in index_names
    assert foreign_key_deletions == {
        "membership_id": "CASCADE",
        "department_id": "CASCADE",
        "approved_by": "SET NULL",
    }
    assert table.c.access_level.server_default is not None
    assert table.c.source.server_default is not None


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
