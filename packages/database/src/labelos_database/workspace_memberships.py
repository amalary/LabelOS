from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_database.models import (
    OrganizationMembership,
    Role,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspaceMembershipRole,
)

LEGACY_MEMBERSHIP_ROLE_ASSIGNMENT_SOURCE = "legacy_membership_role_backfill"
LEGACY_MEMBERSHIP_ROLE_MAPPINGS: dict[str, str] = {
    "owner": "owner",
    "admin": "admin",
    "member": "member",
    "artist": "artist",
}

LEGACY_MEMBERSHIP_ROLE_KEYS = frozenset(LEGACY_MEMBERSHIP_ROLE_MAPPINGS.values())


@dataclass(frozen=True)
class LegacyMembershipRoleBackfillReport:
    inspected_role_counts: dict[str, int]
    mapped_role_counts: dict[str, int]
    unmapped_role_counts: dict[str, int]
    assignments_created: int
    assignments_existing: int


def workspace_membership_role_backfill_id(
    workspace_membership_id: UUID,
    role_id: UUID,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        "labelos-legacy-workspace-membership-role:"
        f"{workspace_membership_id}:{role_id}",
    )


def _joined_at_for_status(status: str) -> datetime | None:
    if status in {"active", "accepted"}:
        return datetime.now(UTC)
    return None


async def get_or_create_profile_for_user(
    session: AsyncSession,
    user: User,
) -> UniversalProfile:
    profile = await session.scalar(
        select(UniversalProfile).where(UniversalProfile.user_id == user.id)
    )
    if profile is not None:
        return profile

    profile = UniversalProfile(
        user_id=user.id,
        display_name=user.display_name,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.profile_image_url,
        primary_email=user.email,
        profile_status="active",
        onboarding_status="not_started",
    )
    session.add(profile)
    await session.flush()
    return profile


async def ensure_workspace_membership_for_organization_membership(
    session: AsyncSession,
    membership: OrganizationMembership,
    *,
    invited_by_profile_id: UUID | None = None,
    joined_at: datetime | None = None,
) -> WorkspaceMembership:
    user = await session.get(User, membership.user_id)
    if user is None:
        raise ValueError("organization membership must reference an existing user")

    profile = await get_or_create_profile_for_user(session, user)
    workspace_membership = await session.scalar(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.organization_membership_id == membership.id,
        )
        .options(selectinload(WorkspaceMembership.organization_membership))
    )
    if workspace_membership is None:
        workspace_membership = await session.scalar(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == membership.organization_id)
            .where(WorkspaceMembership.profile_id == profile.id)
            .options(selectinload(WorkspaceMembership.organization_membership))
        )

    if workspace_membership is None:
        workspace_membership = WorkspaceMembership(
            workspace_id=membership.organization_id,
            profile_id=profile.id,
            organization_membership_id=membership.id,
            status=membership.status,
            invited_by=invited_by_profile_id,
            joined_at=joined_at or _joined_at_for_status(membership.status),
        )
        session.add(workspace_membership)
    else:
        workspace_membership.workspace_id = membership.organization_id
        workspace_membership.profile_id = profile.id
        workspace_membership.organization_membership_id = membership.id
        workspace_membership.status = membership.status
        if workspace_membership.invited_by is None:
            workspace_membership.invited_by = invited_by_profile_id
        if workspace_membership.joined_at is None:
            workspace_membership.joined_at = joined_at or _joined_at_for_status(
                membership.status
            )

    await session.flush()
    return workspace_membership


def _legacy_role_value(membership: OrganizationMembership) -> str:
    role = membership.role
    if hasattr(role, "value"):
        return role.value
    return str(role)


async def backfill_workspace_membership_roles_from_legacy_memberships(
    session: AsyncSession,
) -> LegacyMembershipRoleBackfillReport:
    """Bridge legacy organization membership roles into role assignments.

    The legacy membership role field remains untouched. Unmapped values are reported
    so operators can decide on explicit mappings instead of the migration guessing.
    """

    roles_by_key = {
        role.key: role
        for role in (
            await session.scalars(
                select(Role).where(
                    Role.workspace_id.is_(None),
                    Role.key.in_(LEGACY_MEMBERSHIP_ROLE_KEYS),
                )
            )
        ).all()
    }
    missing_role_keys = sorted(LEGACY_MEMBERSHIP_ROLE_KEYS - roles_by_key.keys())
    if missing_role_keys:
        raise ValueError(
            "system roles must be seeded before backfilling legacy memberships: "
            + ", ".join(missing_role_keys)
        )

    inspected_role_counts: Counter[str] = Counter()
    mapped_role_counts: Counter[str] = Counter()
    unmapped_role_counts: Counter[str] = Counter()
    assignments_created = 0
    assignments_existing = 0

    memberships = (
        await session.scalars(
            select(OrganizationMembership).options(
                selectinload(OrganizationMembership.user)
            )
        )
    ).all()

    for membership in memberships:
        legacy_role = _legacy_role_value(membership)
        inspected_role_counts[legacy_role] += 1
        workspace_membership = (
            await ensure_workspace_membership_for_organization_membership(
                session,
                membership,
            )
        )
        role_key = LEGACY_MEMBERSHIP_ROLE_MAPPINGS.get(legacy_role)
        if role_key is None:
            unmapped_role_counts[legacy_role] += 1
            continue

        role = roles_by_key[role_key]
        existing_assignment = await session.scalar(
            select(WorkspaceMembershipRole)
            .where(WorkspaceMembershipRole.membership_id == workspace_membership.id)
            .where(WorkspaceMembershipRole.role_id == role.id)
        )
        if existing_assignment is not None:
            assignments_existing += 1
            mapped_role_counts[legacy_role] += 1
            continue

        session.add(
            WorkspaceMembershipRole(
                id=workspace_membership_role_backfill_id(
                    workspace_membership.id,
                    role.id,
                ),
                membership_id=workspace_membership.id,
                role_id=role.id,
                metadata_json={
                    "source": LEGACY_MEMBERSHIP_ROLE_ASSIGNMENT_SOURCE,
                    "legacy_role": legacy_role,
                },
            )
        )
        assignments_created += 1
        mapped_role_counts[legacy_role] += 1

    await session.flush()
    return LegacyMembershipRoleBackfillReport(
        inspected_role_counts=dict(sorted(inspected_role_counts.items())),
        mapped_role_counts=dict(sorted(mapped_role_counts.items())),
        unmapped_role_counts=dict(sorted(unmapped_role_counts.items())),
        assignments_created=assignments_created,
        assignments_existing=assignments_existing,
    )


async def mark_workspace_membership_removed(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    profile_id: UUID,
) -> bool:
    workspace_membership = await session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.profile_id == profile_id)
    )
    if workspace_membership is None:
        return False

    workspace_membership.status = "removed"
    if workspace_membership.organization_membership_id is not None:
        await session.execute(
            delete(OrganizationMembership).where(
                OrganizationMembership.id
                == workspace_membership.organization_membership_id
            )
        )
        workspace_membership.organization_membership_id = None
    await session.flush()
    return True
