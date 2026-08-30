"""backfill legacy membership role assignments

Revision ID: 202608261000
Revises: 202608260900
Create Date: 2026-08-26 10:00:00.000000

"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op
from labelos_database.bootstrap import seed_system_roles_and_capabilities

revision: str = "202608261000"
down_revision: str | None = "202608260900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LEGACY_MEMBERSHIP_ROLE_ASSIGNMENT_SOURCE = "legacy_membership_role_backfill"
LEGACY_MEMBERSHIP_ROLE_MAPPINGS = {
    "owner": "owner",
    "admin": "admin",
    "member": "member",
    "artist": "artist",
}


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(
        "ALTER TYPE organization_membership_role ADD VALUE IF NOT EXISTS 'artist'"
    )
    seed_system_roles_and_capabilities(bind)
    _ensure_workspace_memberships(bind)
    inspected_role_counts = _inspect_legacy_role_values(bind)
    report = _backfill_workspace_membership_role_assignments(bind)
    unmapped_role_counts = {
        role: count
        for role, count in inspected_role_counts.items()
        if role not in LEGACY_MEMBERSHIP_ROLE_MAPPINGS
    }
    print(
        "legacy membership role backfill inspected="
        f"{inspected_role_counts} mapped={report['mapped']} "
        f"unmapped={unmapped_role_counts} created={report['created']} "
        f"existing={report['existing']}"
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("""
            DELETE FROM workspace_membership_roles
            WHERE metadata ->> 'source' = :source
            """),
        {"source": LEGACY_MEMBERSHIP_ROLE_ASSIGNMENT_SOURCE},
    )


def _inspect_legacy_role_values(bind: sa.Connection) -> dict[str, int]:
    return {
        row["legacy_role"]: row["membership_count"] for row in bind.execute(sa.text("""
                SELECT role::text AS legacy_role, count(*) AS membership_count
                FROM organization_memberships
                GROUP BY role::text
                ORDER BY role::text
                """)).mappings()
    }


def _ensure_workspace_memberships(bind: sa.Connection) -> None:
    bind.execute(sa.text("""
            INSERT INTO universal_profiles (
                id,
                user_id,
                display_name,
                first_name,
                last_name,
                avatar_url,
                primary_email,
                profile_status,
                onboarding_status
            )
            SELECT
                gen_random_uuid(),
                users.id,
                users.display_name,
                users.first_name,
                users.last_name,
                users.profile_image_url,
                users.email,
                'active',
                'not_started'
            FROM users
            WHERE NOT EXISTS (
                SELECT 1
                FROM universal_profiles
                WHERE universal_profiles.user_id = users.id
            )
            """))
    bind.execute(sa.text("""
            UPDATE workspace_memberships
            SET
                organization_membership_id = organization_memberships.id,
                status = organization_memberships.status
            FROM organization_memberships
            JOIN universal_profiles
                ON universal_profiles.user_id = organization_memberships.user_id
            WHERE workspace_memberships.workspace_id =
                    organization_memberships.organization_id
                AND workspace_memberships.profile_id = universal_profiles.id
                AND workspace_memberships.organization_membership_id IS NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM workspace_memberships existing
                    WHERE existing.organization_membership_id =
                        organization_memberships.id
                )
            """))
    bind.execute(sa.text("""
            INSERT INTO workspace_memberships (
                id,
                workspace_id,
                profile_id,
                organization_membership_id,
                status,
                joined_at
            )
            SELECT
                gen_random_uuid(),
                organization_memberships.organization_id,
                universal_profiles.id,
                organization_memberships.id,
                organization_memberships.status,
                CASE
                    WHEN organization_memberships.status IN ('active', 'accepted')
                        THEN now()
                    ELSE NULL
                END
            FROM organization_memberships
            JOIN universal_profiles
                ON universal_profiles.user_id = organization_memberships.user_id
            WHERE NOT EXISTS (
                    SELECT 1
                    FROM workspace_memberships
                    WHERE workspace_memberships.organization_membership_id =
                        organization_memberships.id
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM workspace_memberships
                    WHERE workspace_memberships.workspace_id =
                            organization_memberships.organization_id
                        AND workspace_memberships.profile_id =
                            universal_profiles.id
                )
            """))


def _backfill_workspace_membership_role_assignments(
    bind: sa.Connection,
) -> dict[str, object]:
    roles_by_key = {
        row["key"]: row["id"]
        for row in bind.execute(
            sa.text("""
                SELECT key, id
                FROM roles
                WHERE workspace_id IS NULL
                    AND key IN :role_keys
                """).bindparams(
                sa.bindparam(
                    "role_keys",
                    tuple(set(LEGACY_MEMBERSHIP_ROLE_MAPPINGS.values())),
                    expanding=True,
                )
            )
        ).mappings()
    }
    missing_role_keys = sorted(
        set(LEGACY_MEMBERSHIP_ROLE_MAPPINGS.values()) - roles_by_key.keys()
    )
    if missing_role_keys:
        raise RuntimeError(
            "system roles must be seeded before backfilling legacy memberships: "
            + ", ".join(missing_role_keys)
        )

    created = 0
    existing = 0
    mapped: dict[str, int] = {}
    rows = bind.execute(sa.text("""
            SELECT
                workspace_memberships.id AS workspace_membership_id,
                organization_memberships.role::text AS legacy_role
            FROM organization_memberships
            JOIN workspace_memberships
                ON workspace_memberships.organization_membership_id =
                    organization_memberships.id
            ORDER BY organization_memberships.id
            """)).mappings()

    for row in rows:
        legacy_role = row["legacy_role"]
        role_key = LEGACY_MEMBERSHIP_ROLE_MAPPINGS.get(legacy_role)
        if role_key is None:
            continue
        role_id = roles_by_key[role_key]
        mapped[legacy_role] = mapped.get(legacy_role, 0) + 1
        if _assignment_exists(bind, row["workspace_membership_id"], role_id):
            existing += 1
            continue
        bind.execute(
            sa.text("""
                INSERT INTO workspace_membership_roles (
                    id,
                    membership_id,
                    role_id,
                    metadata
                )
                VALUES (
                    :id,
                    :membership_id,
                    :role_id,
                    json_build_object(
                        'source',
                        :source,
                        'legacy_role',
                        :legacy_role
                    )
                )
                """),
            {
                "id": uuid5(
                    NAMESPACE_URL,
                    "labelos-legacy-workspace-membership-role:"
                    f"{row['workspace_membership_id']}:{role_id}",
                ),
                "membership_id": row["workspace_membership_id"],
                "role_id": role_id,
                "source": LEGACY_MEMBERSHIP_ROLE_ASSIGNMENT_SOURCE,
                "legacy_role": legacy_role,
            },
        )
        created += 1

    return {"created": created, "existing": existing, "mapped": mapped}


def _assignment_exists(
    bind: sa.Connection,
    workspace_membership_id: object,
    role_id: object,
) -> bool:
    return (
        bind.execute(
            sa.text("""
                SELECT 1
                FROM workspace_membership_roles
                WHERE membership_id = :membership_id
                    AND role_id = :role_id
                """),
            {"membership_id": workspace_membership_id, "role_id": role_id},
        ).scalar_one_or_none()
        is not None
    )
