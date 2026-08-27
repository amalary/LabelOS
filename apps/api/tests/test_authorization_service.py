import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from labelos_database.base import Base
from labelos_database.models import (
    Artist,
    ArtistProfile,
    Department,
    MembershipDepartmentAccess,
    MembershipRole,
    Organization,
    OrganizationMembership,
    Role,
    RoleCapability,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspacePermission,
)
from labelos_database.models import (
    Capability as DBCapability,
)
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.authorization import AuthorizationResource, authorization_service


@dataclass(frozen=True)
class AuthorizationSeed:
    user_id: UUID
    workspace_id: UUID
    other_workspace_id: UUID
    profile_id: UUID
    other_profile_id: UUID
    artist_profile_id: UUID
    other_artist_profile_id: UUID
    ar_role_id: UUID
    manager_role_id: UUID
    other_workspace_role_id: UUID


@pytest.fixture
def authorization_sessionmaker() -> Iterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())
    try:
        yield sessionmaker
    finally:
        asyncio.run(engine.dispose())


async def _seed_authorization_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AuthorizationSeed:
    async with sessionmaker() as session:
        user = User(email="actor@example.com", display_name="Actor")
        owner = User(email="owner@example.com", display_name="Owner")
        workspace = Organization(
            name="Alpha Label",
            slug="alpha-label",
            workos_organization_id="org_ALPHA",
            owner=owner,
        )
        other_workspace = Organization(
            name="Beta Label",
            slug="beta-label",
            workos_organization_id="org_BETA",
            owner=owner,
        )
        profile = UniversalProfile(
            user=user,
            primary_email=user.email,
            display_name=user.display_name,
        )
        other_user = User(email="other@example.com", display_name="Other")
        other_profile = UniversalProfile(
            user=other_user,
            primary_email=other_user.email,
            display_name=other_user.display_name,
        )
        membership = OrganizationMembership(
            organization=workspace,
            user=user,
            role=MembershipRole.guest,
            workspace_permission=WorkspacePermission.guest,
        )
        workspace_membership = WorkspaceMembership(
            workspace=workspace,
            profile=profile,
            organization_membership=membership,
            status="active",
        )
        other_membership = OrganizationMembership(
            organization=other_workspace,
            user=other_user,
            role=MembershipRole.guest,
            workspace_permission=WorkspacePermission.guest,
        )
        other_workspace_membership = WorkspaceMembership(
            workspace=other_workspace,
            profile=other_profile,
            organization_membership=other_membership,
            status="active",
        )
        artist = Artist(
            organization=workspace,
            name="Alpha Artist",
        )
        other_artist = Artist(
            organization=other_workspace,
            name="Beta Artist",
        )
        artist_profile = ArtistProfile(
            artist=artist,
            universal_profile=profile,
            stage_name="Alpha Artist",
        )
        other_artist_profile = ArtistProfile(
            artist=other_artist,
            universal_profile=other_profile,
            stage_name="Beta Artist",
        )
        ar_department = Department(
            slug="a&r",
            display_name="A&R",
            description="Artists and repertoire.",
        )
        management_department = Department(
            slug="management",
            display_name="Management",
            description="Management.",
        )
        ar_role = Role(
            key="a_and_r",
            display_name="A&R",
            description="A&R.",
            system_role=True,
        )
        manager_role = Role(
            key="manager",
            display_name="Manager",
            description="Manager.",
            system_role=True,
        )
        other_workspace_role = Role(
            workspace=other_workspace,
            key="manager",
            display_name="Other Manager",
            description="Other workspace manager.",
        )
        artist_create = DBCapability(
            key="artist.profile.create",
            display_name="Create artist profiles",
            description="Create artist profiles.",
            system_capability=True,
        )
        artist_edit = DBCapability(
            key="artist.profile.edit",
            display_name="Edit artist profiles",
            description="Edit artist profiles.",
            system_capability=True,
        )
        profile_view = DBCapability(
            key="profile.view",
            display_name="View profiles",
            description="View profiles.",
            system_capability=True,
        )
        release_edit = DBCapability(
            key="release.edit",
            display_name="Edit releases",
            description="Edit releases.",
            system_capability=True,
        )
        contract_view = DBCapability(
            key="contract.view",
            display_name="View contracts",
            description="View contracts.",
            system_capability=True,
        )
        session.add_all(
            [
                workspace,
                other_workspace,
                user,
                owner,
                profile,
                other_user,
                other_profile,
                membership,
                workspace_membership,
                other_membership,
                other_workspace_membership,
                artist,
                other_artist,
                artist_profile,
                other_artist_profile,
                ar_department,
                management_department,
                MembershipDepartmentAccess(
                    membership=membership,
                    department=ar_department,
                    access_level="member",
                    source="admin_grant",
                ),
                MembershipDepartmentAccess(
                    membership=membership,
                    department=management_department,
                    access_level="member",
                    source="admin_grant",
                ),
                ar_role,
                manager_role,
                other_workspace_role,
                artist_create,
                artist_edit,
                profile_view,
                release_edit,
                contract_view,
                RoleCapability(role=ar_role, capability=artist_create),
                RoleCapability(role=ar_role, capability=artist_edit),
                RoleCapability(role=ar_role, capability=profile_view),
                RoleCapability(role=manager_role, capability=release_edit),
                RoleCapability(role=other_workspace_role, capability=contract_view),
                WorkspaceMembershipRole(
                    workspace_membership=workspace_membership,
                    role=ar_role,
                ),
                WorkspaceMembershipRole(
                    workspace_membership=workspace_membership,
                    role=manager_role,
                ),
            ]
        )
        await session.commit()
        return AuthorizationSeed(
            user_id=user.id,
            workspace_id=workspace.id,
            other_workspace_id=other_workspace.id,
            profile_id=profile.id,
            other_profile_id=other_profile.id,
            artist_profile_id=artist_profile.id,
            other_artist_profile_id=other_artist_profile.id,
            ar_role_id=ar_role.id,
            manager_role_id=manager_role.id,
            other_workspace_role_id=other_workspace_role.id,
        )


def test_database_authorization_unions_multiple_assigned_roles(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def authorize() -> tuple[bool, bool, bool]:
        async with authorization_sessionmaker() as session:
            return (
                await authorization_service.has_capability(
                    session,
                    seeded.user_id,
                    seeded.workspace_id,
                    "artist.profile.create",
                    AuthorizationResource(
                        workspace_id=seeded.workspace_id,
                        department="a&r",
                    ),
                ),
                await authorization_service.has_capability(
                    session,
                    seeded.user_id,
                    seeded.workspace_id,
                    "release.edit",
                    AuthorizationResource(
                        workspace_id=seeded.workspace_id,
                        department="management",
                    ),
                ),
                await authorization_service.has_capability(
                    session,
                    seeded.user_id,
                    seeded.workspace_id,
                    "contract.view",
                    AuthorizationResource(
                        workspace_id=seeded.workspace_id,
                        department="legal",
                    ),
                ),
            )

    assert asyncio.run(authorize()) == (True, True, False)


def test_database_authorization_allows_resource_in_own_workspace(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def authorize() -> tuple[bool, str]:
        async with authorization_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.user_id,
                workspace=seeded.workspace_id,
                capability="artist.profile.edit",
                resource=AuthorizationResource(
                    kind="artist_profile",
                    id=seeded.artist_profile_id,
                    department="a&r",
                ),
            )
            return decision.allowed, decision.reason

    assert asyncio.run(authorize()) == (True, "capability_allowed")


def test_database_authorization_denies_same_resource_type_in_another_workspace(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def authorize() -> tuple[bool, str]:
        async with authorization_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.user_id,
                workspace=seeded.workspace_id,
                capability="artist.profile.edit",
                resource=AuthorizationResource(
                    kind="artist_profile",
                    id=seeded.other_artist_profile_id,
                    department="a&r",
                ),
            )
            return decision.allowed, decision.reason

    assert asyncio.run(authorize()) == (False, "invalid_resource_scope")


def test_database_authorization_denies_user_with_no_workspace_membership(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def authorize() -> str:
        async with authorization_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.user_id,
                workspace=seeded.other_workspace_id,
                capability="artist.profile.edit",
                resource=AuthorizationResource(
                    kind="artist_profile",
                    id=seeded.other_artist_profile_id,
                    department="a&r",
                ),
            )
            return decision.reason

    assert asyncio.run(authorize()) == "membership_not_found"


def test_database_authorization_removed_role_immediately_affects_access(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def remove_role_and_authorize() -> tuple[bool, bool]:
        async with authorization_sessionmaker() as session:
            before = await authorization_service.has_capability(
                session,
                seeded.user_id,
                seeded.workspace_id,
                "release.edit",
                AuthorizationResource(
                    workspace_id=seeded.workspace_id,
                    department="management",
                ),
            )
            assignment = await session.scalar(
                select(WorkspaceMembershipRole)
                .join(WorkspaceMembershipRole.workspace_membership)
                .where(WorkspaceMembership.workspace_id == seeded.workspace_id)
                .where(WorkspaceMembershipRole.role_id == seeded.manager_role_id)
            )
            assert assignment is not None
            await session.delete(assignment)
            await session.flush()
            after = await authorization_service.has_capability(
                session,
                seeded.user_id,
                seeded.workspace_id,
                "release.edit",
                AuthorizationResource(
                    workspace_id=seeded.workspace_id,
                    department="management",
                ),
            )
            return before, after

    assert asyncio.run(remove_role_and_authorize()) == (True, False)


def test_database_authorization_reuses_loaded_state_within_session(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def authorize_twice() -> tuple[bool, bool, int, int]:
        statement_count = 0

        def count_statement(*_args: object) -> None:
            nonlocal statement_count
            statement_count += 1

        async with authorization_sessionmaker() as session:
            bind = session.get_bind()
            event.listen(bind, "before_cursor_execute", count_statement)
            try:
                first = await authorization_service.has_capability(
                    session,
                    seeded.user_id,
                    seeded.workspace_id,
                    "release.edit",
                    AuthorizationResource(
                        workspace_id=seeded.workspace_id,
                        department="management",
                    ),
                )
                first_count = statement_count
                second = await authorization_service.has_capability(
                    session,
                    seeded.user_id,
                    seeded.workspace_id,
                    "artist.profile.create",
                    AuthorizationResource(
                        workspace_id=seeded.workspace_id,
                        department="a&r",
                    ),
                )
                second_count = statement_count
            finally:
                event.remove(bind, "before_cursor_execute", count_statement)
        return first, second, first_count, second_count

    first, second, first_count, second_count = asyncio.run(authorize_twice())

    assert first is True
    assert second is True
    assert first_count > 0
    assert second_count == first_count


def test_database_authorization_role_capability_change_invalidates_cached_state(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def update_role_capability_and_authorize() -> tuple[bool, bool]:
        async with authorization_sessionmaker() as session:
            manager_assignment = await session.scalar(
                select(WorkspaceMembershipRole)
                .join(WorkspaceMembershipRole.workspace_membership)
                .where(WorkspaceMembership.workspace_id == seeded.workspace_id)
                .where(WorkspaceMembershipRole.role_id == seeded.manager_role_id)
            )
            assert manager_assignment is not None
            await session.delete(manager_assignment)
            await session.flush()

            before = await authorization_service.has_capability(
                session,
                seeded.user_id,
                seeded.workspace_id,
                "release.edit",
                AuthorizationResource(
                    workspace_id=seeded.workspace_id,
                    department="management",
                ),
            )

            release_edit = await session.scalar(
                select(DBCapability).where(DBCapability.key == "release.edit")
            )
            assert release_edit is not None
            session.add(
                RoleCapability(role_id=seeded.ar_role_id, capability_id=release_edit.id)
            )
            await session.flush()

            after = await authorization_service.has_capability(
                session,
                seeded.user_id,
                seeded.workspace_id,
                "release.edit",
                AuthorizationResource(
                    workspace_id=seeded.workspace_id,
                    department="management",
                ),
            )
            return before, after

    assert asyncio.run(update_role_capability_and_authorize()) == (False, True)


def test_database_authorization_denies_deleted_or_invalid_resource(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def authorize() -> str:
        async with authorization_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.user_id,
                workspace=seeded.workspace_id,
                capability="artist.profile.edit",
                resource=AuthorizationResource(
                    kind="artist_profile",
                    id=uuid4(),
                    department="a&r",
                ),
            )
            return decision.reason

    assert asyncio.run(authorize()) == "invalid_resource_scope"


def test_database_authorization_denies_cross_workspace_profile_before_capability(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def authorize() -> tuple[bool, str]:
        async with authorization_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.user_id,
                workspace=seeded.workspace_id,
                capability="profile.view",
                resource=AuthorizationResource(
                    kind="profile",
                    id=seeded.other_profile_id,
                ),
            )
            return decision.allowed, decision.reason

    assert asyncio.run(authorize()) == (False, "invalid_resource_scope")


def test_database_authorization_denies_unknown_capability(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def authorize() -> str:
        async with authorization_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.user_id,
                workspace=seeded.workspace_id,
                capability="unregistered.action",
            )
            return decision.reason

    assert asyncio.run(authorize()) == "unknown_capability"


def test_database_authorization_denies_missing_workspace_membership(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def authorize() -> str:
        async with authorization_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=uuid4(),
                workspace=seeded.workspace_id,
                capability="artist.profile.create",
            )
            return decision.reason

    assert asyncio.run(authorize()) == "membership_not_found"


def test_database_authorization_denies_invalid_resource_scope(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def authorize() -> str:
        async with authorization_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.user_id,
                workspace=seeded.workspace_id,
                capability="artist.profile.create",
                resource={
                    "workspace_id": str(seeded.workspace_id),
                    "department": "a&r",
                },
            )
            return decision.reason

    assert asyncio.run(authorize()) == "invalid_resource_scope"


def test_database_authorization_denies_cross_workspace_role_mapping(
    authorization_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_authorization_data(authorization_sessionmaker))

    async def assign_invalid_role_and_authorize() -> str:
        async with authorization_sessionmaker() as session:
            membership = await session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == seeded.workspace_id
                )
            )
            assert membership is not None
            session.add(
                WorkspaceMembershipRole(
                    membership_id=membership.id,
                    role_id=seeded.other_workspace_role_id,
                )
            )
            await session.commit()

        async with authorization_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.user_id,
                workspace=seeded.workspace_id,
                capability="artist.profile.create",
                resource=AuthorizationResource(
                    workspace_id=seeded.workspace_id,
                    department="a&r",
                ),
            )
            return decision.reason

    assert asyncio.run(assign_invalid_role_and_authorize()) == "invalid_role_mapping"
