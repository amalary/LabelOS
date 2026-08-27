import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from labelos_database.base import Base
from labelos_database.bootstrap import seed_system_roles_and_capabilities
from labelos_database.capabilities import Capability
from labelos_database.models import (
    Artist,
    ArtistProfile,
    MembershipRole,
    Organization,
    OrganizationMembership,
    Role,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspacePermission,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.authorization import (
    CAPABILITY_DEPARTMENTS,
    AuthorizationResource,
    ResourceKind,
    authorization_service,
)

SYSTEM_ROLE_KEYS = (
    "owner",
    "admin",
    "artist",
    "a_and_r",
    "manager",
    "legal",
    "marketing",
    "finance",
    "producer",
)

ALL_DEPARTMENTS = sorted(
    {
        department
        for departments in CAPABILITY_DEPARTMENTS.values()
        for department in departments
    }
)


@dataclass(frozen=True)
class MatrixAction:
    name: str
    capability: Capability
    department: str
    target: str
    allowed_roles: frozenset[str]


PERMISSION_MATRIX = (
    MatrixAction(
        name="artist edits own accessible artist profile",
        capability=Capability.artist_profile_edit,
        department="artist",
        target="own_artist_profile",
        allowed_roles=frozenset({"owner", "admin", "artist", "a_and_r", "manager"}),
    ),
    MatrixAction(
        name="artist attempts administrative workspace action",
        capability=Capability.workspace_update,
        department="administration",
        target="workspace",
        allowed_roles=frozenset({"owner", "admin"}),
    ),
    MatrixAction(
        name="A&R views workspace artists",
        capability=Capability.artist_profile_view,
        department="a&r",
        target="coworker_artist_profile",
        allowed_roles=frozenset(
            {"owner", "admin", "artist", "a_and_r", "manager", "marketing", "producer"}
        ),
    ),
    MatrixAction(
        name="A&R attempts contract approval",
        capability=Capability.contract_approve,
        department="legal",
        target="workspace",
        allowed_roles=frozenset({"owner", "legal"}),
    ),
    MatrixAction(
        name="legal views contract",
        capability=Capability.contract_view,
        department="legal",
        target="workspace",
        allowed_roles=frozenset({"owner", "admin", "manager", "legal", "finance"}),
    ),
    MatrixAction(
        name="legal approves contract",
        capability=Capability.contract_approve,
        department="legal",
        target="workspace",
        allowed_roles=frozenset({"owner", "legal"}),
    ),
    MatrixAction(
        name="marketing attempts contract approval",
        capability=Capability.contract_approve,
        department="legal",
        target="workspace",
        allowed_roles=frozenset({"owner", "legal"}),
    ),
    MatrixAction(
        name="manager edits allowed artist information",
        capability=Capability.artist_profile_edit,
        department="management",
        target="coworker_artist_profile",
        allowed_roles=frozenset({"owner", "admin", "a_and_r", "manager"}),
    ),
    MatrixAction(
        name="finance accesses finance capability",
        capability=Capability.finance_view,
        department="finance",
        target="workspace",
        allowed_roles=frozenset({"owner", "admin", "finance"}),
    ),
    MatrixAction(
        name="unauthorized member attempts role assignment",
        capability=Capability.role_assign,
        department="administration",
        target="workspace",
        allowed_roles=frozenset({"owner", "admin"}),
    ),
)


@dataclass(frozen=True)
class MatrixSeed:
    workspace_id: UUID
    other_workspace_id: UUID
    role_user_ids: dict[str, UUID]
    role_profile_ids: dict[str, UUID]
    role_artist_profile_ids: dict[str, UUID]
    role_ids: dict[str, UUID]
    coworker_artist_profile_id: UUID
    other_workspace_artist_profile_id: UUID
    dual_role_user_id: UUID
    dual_role_workspace_membership_id: UUID
    legal_role_id: UUID
    marketing_role_id: UUID
    unauthorized_user_id: UUID


@pytest.fixture
def matrix_sessionmaker() -> Iterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(seed_system_roles_and_capabilities)

    asyncio.run(prepare_database())
    try:
        yield sessionmaker
    finally:
        asyncio.run(engine.dispose())


async def _seed_matrix_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> MatrixSeed:
    async with sessionmaker() as session:
        owner = User(
            email="workspace-owner@example.com", display_name="Workspace Owner"
        )
        workspace = Organization(
            name="Matrix Label",
            slug=f"matrix-label-{uuid4()}",
            workos_organization_id=f"org_{uuid4().hex}",
            owner=owner,
        )
        other_workspace = Organization(
            name="Other Matrix Label",
            slug=f"other-matrix-label-{uuid4()}",
            workos_organization_id=f"org_{uuid4().hex}",
            owner=owner,
        )
        session.add_all([owner, workspace, other_workspace])
        await session.flush()

        roles = {
            role.key: role
            for role in (
                await session.scalars(
                    select(Role).where(Role.key.in_(SYSTEM_ROLE_KEYS))
                )
            ).all()
        }
        assert set(SYSTEM_ROLE_KEYS) <= set(roles)

        role_user_ids: dict[str, UUID] = {}
        role_profile_ids: dict[str, UUID] = {}
        role_artist_profile_ids: dict[str, UUID] = {}
        for role_key in SYSTEM_ROLE_KEYS:
            user = User(
                email=f"{role_key.replace('_', '-')}-matrix@example.com",
                display_name=f"{role_key} Matrix",
            )
            profile = UniversalProfile(
                user=user,
                primary_email=user.email,
                display_name=user.display_name,
            )
            membership = OrganizationMembership(
                organization=workspace,
                user=user,
                role=MembershipRole.member,
                workspace_permission=(
                    WorkspacePermission.owner
                    if role_key == "owner"
                    else WorkspacePermission.guest
                ),
                department_access=list(ALL_DEPARTMENTS),
            )
            workspace_membership = WorkspaceMembership(
                workspace=workspace,
                profile=profile,
                organization_membership=membership,
                status="active",
            )
            artist = Artist(
                organization=workspace,
                name=f"{role_key.replace('_', ' ').title()} Artist",
            )
            artist_profile = ArtistProfile(
                artist=artist,
                universal_profile=profile,
                stage_name=artist.name,
            )
            session.add_all(
                [
                    user,
                    profile,
                    membership,
                    workspace_membership,
                    WorkspaceMembershipRole(
                        workspace_membership=workspace_membership,
                        role=roles[role_key],
                    ),
                    artist,
                    artist_profile,
                ]
            )
            await session.flush()
            role_user_ids[role_key] = user.id
            role_profile_ids[role_key] = profile.id
            role_artist_profile_ids[role_key] = artist_profile.id

        coworker_user = User(
            email="coworker-artist@example.com",
            display_name="Coworker Artist",
        )
        coworker_profile = UniversalProfile(
            user=coworker_user,
            primary_email=coworker_user.email,
            display_name=coworker_user.display_name,
        )
        coworker_membership = OrganizationMembership(
            organization=workspace,
            user=coworker_user,
            role=MembershipRole.member,
            workspace_permission=WorkspacePermission.member,
        )
        coworker_workspace_membership = WorkspaceMembership(
            workspace=workspace,
            profile=coworker_profile,
            organization_membership=coworker_membership,
            status="active",
        )
        coworker_artist = Artist(organization=workspace, name="Coworker")
        coworker_artist_profile = ArtistProfile(
            artist=coworker_artist,
            universal_profile=coworker_profile,
            stage_name="Coworker",
        )

        other_user = User(email="other-workspace@example.com", display_name="Other")
        other_profile = UniversalProfile(
            user=other_user,
            primary_email=other_user.email,
            display_name=other_user.display_name,
        )
        other_membership = OrganizationMembership(
            organization=other_workspace,
            user=other_user,
            role=MembershipRole.member,
            workspace_permission=WorkspacePermission.member,
        )
        other_workspace_membership = WorkspaceMembership(
            workspace=other_workspace,
            profile=other_profile,
            organization_membership=other_membership,
            status="active",
        )
        other_artist = Artist(
            organization=other_workspace, name="Other Workspace Artist"
        )
        other_artist_profile = ArtistProfile(
            artist=other_artist,
            universal_profile=other_profile,
            stage_name="Other Workspace Artist",
        )

        dual_role_user = User(email="dual-role@example.com", display_name="Dual Role")
        dual_role_profile = UniversalProfile(
            user=dual_role_user,
            primary_email=dual_role_user.email,
            display_name=dual_role_user.display_name,
        )
        dual_role_membership = OrganizationMembership(
            organization=workspace,
            user=dual_role_user,
            role=MembershipRole.member,
            workspace_permission=WorkspacePermission.guest,
            department_access=list(ALL_DEPARTMENTS),
        )
        dual_role_workspace_membership = WorkspaceMembership(
            workspace=workspace,
            profile=dual_role_profile,
            organization_membership=dual_role_membership,
            status="active",
        )

        unauthorized_user = User(
            email="unauthorized-member@example.com",
            display_name="Unauthorized Member",
        )
        unauthorized_profile = UniversalProfile(
            user=unauthorized_user,
            primary_email=unauthorized_user.email,
            display_name=unauthorized_user.display_name,
        )
        unauthorized_membership = OrganizationMembership(
            organization=workspace,
            user=unauthorized_user,
            role=MembershipRole.member,
            workspace_permission=WorkspacePermission.guest,
            department_access=list(ALL_DEPARTMENTS),
        )
        unauthorized_workspace_membership = WorkspaceMembership(
            workspace=workspace,
            profile=unauthorized_profile,
            organization_membership=unauthorized_membership,
            status="active",
        )

        session.add_all(
            [
                coworker_user,
                coworker_profile,
                coworker_membership,
                coworker_workspace_membership,
                coworker_artist,
                coworker_artist_profile,
                other_user,
                other_profile,
                other_membership,
                other_workspace_membership,
                other_artist,
                other_artist_profile,
                dual_role_user,
                dual_role_profile,
                dual_role_membership,
                dual_role_workspace_membership,
                WorkspaceMembershipRole(
                    workspace_membership=dual_role_workspace_membership,
                    role=roles["legal"],
                ),
                WorkspaceMembershipRole(
                    workspace_membership=dual_role_workspace_membership,
                    role=roles["marketing"],
                ),
                unauthorized_user,
                unauthorized_profile,
                unauthorized_membership,
                unauthorized_workspace_membership,
            ]
        )
        await session.commit()

        return MatrixSeed(
            workspace_id=workspace.id,
            other_workspace_id=other_workspace.id,
            role_user_ids=role_user_ids,
            role_profile_ids=role_profile_ids,
            role_artist_profile_ids=role_artist_profile_ids,
            role_ids={key: role.id for key, role in roles.items()},
            coworker_artist_profile_id=coworker_artist_profile.id,
            other_workspace_artist_profile_id=other_artist_profile.id,
            dual_role_user_id=dual_role_user.id,
            dual_role_workspace_membership_id=dual_role_workspace_membership.id,
            legal_role_id=roles["legal"].id,
            marketing_role_id=roles["marketing"].id,
            unauthorized_user_id=unauthorized_user.id,
        )


def _resource_for_action(
    seed: MatrixSeed, role_key: str, action: MatrixAction
) -> AuthorizationResource:
    if action.target == "own_artist_profile":
        return AuthorizationResource(
            kind=ResourceKind.artist_profile,
            id=seed.role_artist_profile_ids[role_key],
            workspace_id=seed.workspace_id,
            department=action.department,
        )
    if action.target == "coworker_artist_profile":
        return AuthorizationResource(
            kind=ResourceKind.artist_profile,
            id=seed.coworker_artist_profile_id,
            workspace_id=seed.workspace_id,
            department=action.department,
        )
    return AuthorizationResource(
        workspace_id=seed.workspace_id, department=action.department
    )


@pytest.mark.parametrize("role_key", SYSTEM_ROLE_KEYS)
@pytest.mark.parametrize("action", PERMISSION_MATRIX, ids=lambda action: action.name)
def test_system_role_permission_matrix_authorizes_effective_capabilities(
    matrix_sessionmaker: async_sessionmaker[AsyncSession],
    role_key: str,
    action: MatrixAction,
) -> None:
    seeded = asyncio.run(_seed_matrix_data(matrix_sessionmaker))

    async def authorize() -> tuple[bool, str]:
        async with matrix_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.role_user_ids[role_key],
                workspace=seeded.workspace_id,
                capability=action.capability,
                resource=_resource_for_action(seeded, role_key, action),
            )
            return decision.allowed, decision.reason

    allowed, reason = asyncio.run(authorize())
    expected_allowed = role_key in action.allowed_roles
    assert allowed is expected_allowed
    if expected_allowed:
        assert reason in {"capability_allowed", "workspace_owner"}
    elif role_key == "artist" and action.target == "coworker_artist_profile":
        assert reason == "resource_owner_mismatch"
    else:
        assert reason == "missing_capability"


def test_user_cannot_access_another_workspace(
    matrix_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_matrix_data(matrix_sessionmaker))

    async def authorize() -> tuple[bool, str]:
        async with matrix_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.role_user_ids["artist"],
                workspace=seeded.other_workspace_id,
                capability=Capability.artist_profile_view,
                resource=AuthorizationResource(
                    kind=ResourceKind.artist_profile,
                    id=seeded.other_workspace_artist_profile_id,
                    workspace_id=seeded.other_workspace_id,
                    department="artist",
                ),
            )
            return decision.allowed, decision.reason

    assert asyncio.run(authorize()) == (False, "membership_not_found")


def test_user_holding_two_roles_receives_union_of_effective_capabilities(
    matrix_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_matrix_data(matrix_sessionmaker))

    async def authorize() -> tuple[bool, bool]:
        async with matrix_sessionmaker() as session:
            contract_decision = await authorization_service.decide_capability(
                session,
                actor=seeded.dual_role_user_id,
                workspace=seeded.workspace_id,
                capability=Capability.contract_approve,
                resource=AuthorizationResource(
                    workspace_id=seeded.workspace_id,
                    department="legal",
                ),
            )
            campaign_decision = await authorization_service.decide_capability(
                session,
                actor=seeded.dual_role_user_id,
                workspace=seeded.workspace_id,
                capability=Capability.marketing_campaign_approve,
                resource=AuthorizationResource(
                    workspace_id=seeded.workspace_id,
                    department="marketing",
                ),
            )
            return contract_decision.allowed, campaign_decision.allowed

    assert asyncio.run(authorize()) == (True, True)


def test_user_losing_one_role_loses_only_that_roles_effective_capabilities(
    matrix_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_matrix_data(matrix_sessionmaker))

    async def remove_marketing_role_and_authorize() -> tuple[bool, bool]:
        async with matrix_sessionmaker() as session:
            await session.execute(
                delete(WorkspaceMembershipRole)
                .where(
                    WorkspaceMembershipRole.membership_id
                    == seeded.dual_role_workspace_membership_id
                )
                .where(WorkspaceMembershipRole.role_id == seeded.marketing_role_id)
            )
            await session.flush()
            contract_decision = await authorization_service.decide_capability(
                session,
                actor=seeded.dual_role_user_id,
                workspace=seeded.workspace_id,
                capability=Capability.contract_approve,
                resource=AuthorizationResource(
                    workspace_id=seeded.workspace_id,
                    department="legal",
                ),
            )
            campaign_decision = await authorization_service.decide_capability(
                session,
                actor=seeded.dual_role_user_id,
                workspace=seeded.workspace_id,
                capability=Capability.marketing_campaign_approve,
                resource=AuthorizationResource(
                    workspace_id=seeded.workspace_id,
                    department="marketing",
                ),
            )
            return contract_decision.allowed, campaign_decision.allowed

    assert asyncio.run(remove_marketing_role_and_authorize()) == (True, False)


def test_user_losing_all_roles_loses_all_role_derived_capabilities(
    matrix_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_matrix_data(matrix_sessionmaker))

    async def remove_all_roles_and_authorize() -> tuple[bool, str]:
        async with matrix_sessionmaker() as session:
            await session.execute(
                delete(WorkspaceMembershipRole).where(
                    WorkspaceMembershipRole.membership_id
                    == seeded.dual_role_workspace_membership_id
                )
            )
            await session.flush()
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.dual_role_user_id,
                workspace=seeded.workspace_id,
                capability=Capability.contract_approve,
                resource=AuthorizationResource(
                    workspace_id=seeded.workspace_id,
                    department="legal",
                ),
            )
            return decision.allowed, decision.reason

    assert asyncio.run(remove_all_roles_and_authorize()) == (
        False,
        "missing_capability",
    )


def test_removed_membership_loses_all_authorization(
    matrix_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_matrix_data(matrix_sessionmaker))

    async def remove_membership_and_authorize() -> tuple[bool, str]:
        async with matrix_sessionmaker() as session:
            membership = await session.scalar(
                select(OrganizationMembership)
                .where(OrganizationMembership.user_id == seeded.dual_role_user_id)
                .where(OrganizationMembership.organization_id == seeded.workspace_id)
            )
            workspace_membership = await session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.id == seeded.dual_role_workspace_membership_id
                )
            )
            assert membership is not None
            assert workspace_membership is not None
            membership.status = "removed"
            workspace_membership.status = "removed"
            await session.flush()
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.dual_role_user_id,
                workspace=seeded.workspace_id,
                capability=Capability.contract_approve,
                resource=AuthorizationResource(
                    workspace_id=seeded.workspace_id,
                    department="legal",
                ),
            )
            return decision.allowed, decision.reason

    assert asyncio.run(remove_membership_and_authorize()) == (
        False,
        "membership_not_found",
    )


def test_privilege_escalation_denies_lateral_artist_profile_edit(
    matrix_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_matrix_data(matrix_sessionmaker))

    async def authorize() -> tuple[bool, str]:
        async with matrix_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.role_user_ids["artist"],
                workspace=seeded.workspace_id,
                capability=Capability.artist_profile_edit,
                resource=AuthorizationResource(
                    kind=ResourceKind.artist_profile,
                    id=seeded.coworker_artist_profile_id,
                    workspace_id=seeded.workspace_id,
                    department="artist",
                ),
            )
            return decision.allowed, decision.reason

    assert asyncio.run(authorize()) == (False, "resource_owner_mismatch")


def test_privilege_escalation_denies_forged_resource_workspace_scope(
    matrix_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_matrix_data(matrix_sessionmaker))

    async def authorize() -> tuple[bool, str]:
        async with matrix_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.role_user_ids["manager"],
                workspace=seeded.workspace_id,
                capability=Capability.artist_profile_edit,
                resource=AuthorizationResource(
                    kind=ResourceKind.artist_profile,
                    id=seeded.coworker_artist_profile_id,
                    workspace_id=seeded.other_workspace_id,
                    department="management",
                ),
            )
            return decision.allowed, decision.reason

    assert asyncio.run(authorize()) == (False, "invalid_resource_scope")


def test_unauthorized_member_cannot_assign_roles(
    matrix_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seeded = asyncio.run(_seed_matrix_data(matrix_sessionmaker))

    async def authorize() -> tuple[bool, str]:
        async with matrix_sessionmaker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.unauthorized_user_id,
                workspace=seeded.workspace_id,
                capability=Capability.role_assign,
                resource=AuthorizationResource(
                    workspace_id=seeded.workspace_id,
                    department="administration",
                ),
            )
            return decision.allowed, decision.reason

    assert asyncio.run(authorize()) == (False, "missing_capability")
