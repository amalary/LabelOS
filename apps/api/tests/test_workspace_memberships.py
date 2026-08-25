import asyncio
from collections.abc import Iterator

import pytest
from labelos_database.base import Base
from labelos_database.models import (
    Capability,
    Department,
    MembershipDepartmentAccess,
    MembershipProfessionalRole,
    MembershipRole,
    Organization,
    OrganizationMembership,
    ProfessionalRole,
    Role,
    RoleCapability,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspaceMembershipRole,
)
from labelos_database.workspace_memberships import (
    ensure_workspace_membership_for_organization_membership,
    mark_workspace_membership_removed,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool


@pytest.fixture
def sessionmaker() -> Iterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())
    yield async_sessionmaker(bind=engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


async def _seed_membership(
    session: AsyncSession,
    *,
    email: str = "member@example.com",
    slug: str = "alpha-label",
    role: MembershipRole = MembershipRole.member,
) -> OrganizationMembership:
    user = User(email=email, display_name="Member")
    owner = User(email=f"owner-{slug}@example.com", display_name="Owner")
    organization = Organization(
        name=slug.replace("-", " ").title(), slug=slug, owner=owner
    )
    membership = OrganizationMembership(
        organization=organization,
        user=user,
        role=role,
        status="active",
        workos_membership_id=f"om_{slug}",
    )
    session.add(membership)
    await session.flush()
    return membership


async def _workspace_membership(
    sessionmaker: async_sessionmaker[AsyncSession],
    membership_id,
) -> WorkspaceMembership | None:
    async with sessionmaker() as session:
        return await session.scalar(
            select(WorkspaceMembership)
            .options(
                selectinload(WorkspaceMembership.profile),
                selectinload(WorkspaceMembership.organization_membership)
                .selectinload(OrganizationMembership.professional_role_links)
                .selectinload(MembershipProfessionalRole.professional_role),
                selectinload(WorkspaceMembership.organization_membership)
                .selectinload(OrganizationMembership.department_access_grants)
                .selectinload(MembershipDepartmentAccess.department),
                selectinload(WorkspaceMembership.role_assignments).selectinload(
                    WorkspaceMembershipRole.role
                ),
                selectinload(WorkspaceMembership.role_assignments)
                .selectinload(WorkspaceMembershipRole.role)
                .selectinload(Role.capability_links)
                .selectinload(RoleCapability.capability),
            )
            .where(WorkspaceMembership.organization_membership_id == membership_id)
        )


def test_new_workspace_membership_links_profile_workspace_roles_and_departments(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> WorkspaceMembership:
        async with sessionmaker() as session:
            membership = await _seed_membership(
                session,
                role=MembershipRole.admin,
            )
            role = ProfessionalRole(
                slug="legal",
                display_name="Legal",
                description="Legal counsel.",
            )
            department = Department(
                slug="contracts",
                display_name="Contracts",
                description="Contract review.",
            )
            session.add_all(
                [
                    role,
                    department,
                    MembershipProfessionalRole(
                        membership=membership,
                        professional_role=role,
                        is_primary=True,
                    ),
                    MembershipDepartmentAccess(
                        membership=membership,
                        department=department,
                        access_level="member",
                        source="invitation",
                    ),
                ]
            )
            workspace_membership = (
                await ensure_workspace_membership_for_organization_membership(
                    session,
                    membership,
                )
            )
            await session.commit()
            assert workspace_membership.id is not None
            return workspace_membership

    created = asyncio.run(run())
    loaded = asyncio.run(
        _workspace_membership(sessionmaker, created.organization_membership_id)
    )

    assert loaded is not None
    assert loaded.profile.primary_email == "member@example.com"
    assert loaded.status == "active"
    assert loaded.joined_at is not None
    assert loaded.workspace_permission == "admin"
    assert loaded.professional_roles == ("Legal",)
    assert loaded.department_access == ("contracts",)


def test_existing_workspace_membership_is_reused_for_existing_membership(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[str, str]:
        async with sessionmaker() as session:
            membership = await _seed_membership(session)
            profile = UniversalProfile(
                user_id=membership.user_id,
                display_name="Existing Profile",
                primary_email="member@example.com",
            )
            session.add(profile)
            await session.flush()
            existing = WorkspaceMembership(
                workspace_id=membership.organization_id,
                profile_id=profile.id,
                status="invited",
            )
            session.add(existing)
            await session.flush()
            existing_id = str(existing.id)

            ensured = await ensure_workspace_membership_for_organization_membership(
                session,
                membership,
            )
            await session.commit()
            return existing_id, str(ensured.id)

    existing_id, ensured_id = asyncio.run(run())

    assert ensured_id == existing_id


def test_workspace_membership_duplicate_prevention(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> None:
        async with sessionmaker() as session:
            membership = await _seed_membership(session)
            first = await ensure_workspace_membership_for_organization_membership(
                session,
                membership,
            )
            second = await ensure_workspace_membership_for_organization_membership(
                session,
                membership,
            )
            count = await session.scalar(
                select(func.count()).select_from(WorkspaceMembership)
            )

            duplicate = WorkspaceMembership(
                workspace_id=first.workspace_id,
                profile_id=first.profile_id,
                organization_membership_id=membership.id,
            )
            session.add(duplicate)

            assert first.id == second.id
            assert count == 1
            with pytest.raises(IntegrityError):
                await session.commit()

    asyncio.run(run())


def test_workspace_membership_removal_marks_profile_membership_removed(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, WorkspaceMembership, int]:
        async with sessionmaker() as session:
            membership = await _seed_membership(session)
            workspace_membership = (
                await ensure_workspace_membership_for_organization_membership(
                    session,
                    membership,
                )
            )
            removed = await mark_workspace_membership_removed(
                session,
                workspace_id=workspace_membership.workspace_id,
                profile_id=workspace_membership.profile_id,
            )
            membership_count = await session.scalar(
                select(func.count()).select_from(OrganizationMembership)
            )
            await session.commit()
            return removed, workspace_membership, membership_count or 0

    removed, workspace_membership, membership_count = asyncio.run(run())

    assert removed is True
    assert workspace_membership.status == "removed"
    assert workspace_membership.organization_membership_id is None
    assert membership_count == 0


def test_same_profile_can_belong_to_multiple_workspaces(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[int, int]:
        async with sessionmaker() as session:
            first = await _seed_membership(session, slug="alpha-label")
            await session.flush()
            user = await session.get(User, first.user_id)
            owner = User(email="owner-beta@example.com", display_name="Beta Owner")
            second_org = Organization(name="Beta Label", slug="beta-label", owner=owner)
            second = OrganizationMembership(
                organization=second_org,
                user=user,
                role=MembershipRole.member,
                status="active",
                workos_membership_id="om_beta",
            )
            session.add(second)
            await session.flush()

            first_workspace_membership = (
                await ensure_workspace_membership_for_organization_membership(
                    session,
                    first,
                )
            )
            second_workspace_membership = (
                await ensure_workspace_membership_for_organization_membership(
                    session,
                    second,
                )
            )
            workspace_count = await session.scalar(
                select(func.count()).select_from(WorkspaceMembership)
            )
            await session.commit()
            return (
                workspace_count or 0,
                int(
                    first_workspace_membership.profile_id
                    == second_workspace_membership.profile_id
                ),
            )

    workspace_count, same_profile = asyncio.run(run())

    assert workspace_count == 2
    assert same_profile == 1


def test_workspace_membership_can_hold_multiple_workspace_roles(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> WorkspaceMembership:
        async with sessionmaker() as session:
            membership = await _seed_membership(session)
            workspace_membership = (
                await ensure_workspace_membership_for_organization_membership(
                    session,
                    membership,
                )
            )
            artist = Role(
                key="artist",
                display_name="Artist",
                description="Artist role.",
                system_role=True,
            )
            marketing = Role(
                key="marketing",
                display_name="Marketing",
                description="Marketing role.",
                system_role=True,
            )
            session.add_all(
                [
                    artist,
                    marketing,
                    WorkspaceMembershipRole(
                        workspace_membership=workspace_membership,
                        role=artist,
                    ),
                    WorkspaceMembershipRole(
                        workspace_membership=workspace_membership,
                        role=marketing,
                    ),
                ]
            )
            await session.commit()
            return workspace_membership

    created = asyncio.run(run())
    loaded = asyncio.run(
        _workspace_membership(sessionmaker, created.organization_membership_id)
    )

    assert loaded is not None
    assert loaded.profile.primary_email == "member@example.com"
    assert loaded.role_keys == ("artist", "marketing")


def test_workspace_membership_combines_capabilities_from_multiple_roles(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> WorkspaceMembership:
        async with sessionmaker() as session:
            membership = await _seed_membership(session)
            workspace_membership = (
                await ensure_workspace_membership_for_organization_membership(
                    session,
                    membership,
                )
            )
            legal = Role(
                key="legal",
                display_name="Legal",
                description="Legal role.",
                system_role=True,
            )
            marketing = Role(
                key="marketing",
                display_name="Marketing",
                description="Marketing role.",
                system_role=True,
            )
            contract_view = Capability(
                key="contract.view",
                display_name="View contracts",
                description="View contract records.",
                system_capability=True,
            )
            campaign_approve = Capability(
                key="campaign.approve",
                display_name="Approve campaigns",
                description="Approve campaign plans.",
                system_capability=True,
            )
            session.add_all(
                [
                    legal,
                    marketing,
                    contract_view,
                    campaign_approve,
                    RoleCapability(role=legal, capability=contract_view),
                    RoleCapability(role=marketing, capability=campaign_approve),
                    WorkspaceMembershipRole(
                        workspace_membership=workspace_membership,
                        role=legal,
                    ),
                    WorkspaceMembershipRole(
                        workspace_membership=workspace_membership,
                        role=marketing,
                    ),
                ]
            )
            await session.commit()
            return workspace_membership

    created = asyncio.run(run())
    loaded = asyncio.run(
        _workspace_membership(sessionmaker, created.organization_membership_id)
    )

    assert loaded is not None
    assert loaded.capability_keys == ("contract.view", "campaign.approve")


def test_workspace_role_assignments_are_workspace_specific(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[tuple[str, ...], tuple[str, ...]]:
        async with sessionmaker() as session:
            first = await _seed_membership(session, slug="alpha-label")
            await session.flush()
            user = await session.get(User, first.user_id)
            owner = User(email="owner-beta@example.com", display_name="Beta Owner")
            second_org = Organization(name="Beta Label", slug="beta-label", owner=owner)
            second = OrganizationMembership(
                organization=second_org,
                user=user,
                role=MembershipRole.member,
                status="active",
                workos_membership_id="om_beta",
            )
            session.add(second)
            await session.flush()

            first_workspace = (
                await ensure_workspace_membership_for_organization_membership(
                    session,
                    first,
                )
            )
            second_workspace = (
                await ensure_workspace_membership_for_organization_membership(
                    session,
                    second,
                )
            )
            artist = Role(
                key="artist",
                display_name="Artist",
                description="Artist role.",
                system_role=True,
            )
            manager = Role(
                key="manager",
                display_name="Manager",
                description="Manager role.",
                system_role=True,
            )
            session.add_all(
                [
                    artist,
                    manager,
                    WorkspaceMembershipRole(
                        workspace_membership=first_workspace,
                        role=artist,
                    ),
                    WorkspaceMembershipRole(
                        workspace_membership=second_workspace,
                        role=manager,
                    ),
                ]
            )
            await session.commit()

            first_loaded = await session.scalar(
                select(WorkspaceMembership)
                .options(
                    selectinload(WorkspaceMembership.role_assignments).selectinload(
                        WorkspaceMembershipRole.role
                    )
                )
                .where(WorkspaceMembership.id == first_workspace.id)
            )
            second_loaded = await session.scalar(
                select(WorkspaceMembership)
                .options(
                    selectinload(WorkspaceMembership.role_assignments).selectinload(
                        WorkspaceMembershipRole.role
                    )
                )
                .where(WorkspaceMembership.id == second_workspace.id)
            )
            assert first_loaded is not None
            assert second_loaded is not None
            return first_loaded.role_keys, second_loaded.role_keys

    first_role_keys, second_role_keys = asyncio.run(run())

    assert first_role_keys == ("artist",)
    assert second_role_keys == ("manager",)
