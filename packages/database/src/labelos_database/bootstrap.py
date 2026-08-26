from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from labelos_database.models import Capability, Role, RoleCapability
from labelos_database.roles import (
    DEFAULT_CAPABILITIES,
    DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS,
    DEFAULT_ROLES,
)


def role_capability_id(role_key: str, capability_key: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"labelos-role-capability:{role_key}:{capability_key}",
    )


def seed_system_roles_and_capabilities(connection: Connection) -> None:
    """Idempotently seed global system roles, capabilities, and default links."""

    _seed_capabilities(connection)
    _seed_roles(connection)
    _seed_role_capabilities(connection)


def _seed_capabilities(connection: Connection) -> None:
    table = Capability.__table__
    for capability in DEFAULT_CAPABILITIES:
        existing_id = connection.execute(
            sa.select(table.c.id).where(table.c.key == capability.key)
        ).scalar_one_or_none()
        values = {
            "key": capability.key,
            "display_name": capability.display_name,
            "description": capability.description,
            "system_capability": capability.system_capability,
        }
        if existing_id is None:
            connection.execute(table.insert().values(id=UUID(capability.id), **values))
        else:
            connection.execute(
                table.update().where(table.c.id == existing_id).values(**values)
            )


def _seed_roles(connection: Connection) -> None:
    table = Role.__table__
    for role in DEFAULT_ROLES:
        role_id = UUID(role.id)
        existing_id = connection.execute(
            sa.select(table.c.id).where(
                table.c.workspace_id.is_(None),
                sa.or_(table.c.key == role.key, table.c.id == role_id),
            )
        ).scalar_one_or_none()
        values = {
            "workspace_id": None,
            "key": role.key,
            "name": role.display_name,
            "display_name": role.display_name,
            "description": role.description,
            "is_system_role": role.system_role,
            "system_role": role.system_role,
        }
        if existing_id is None:
            connection.execute(table.insert().values(id=role_id, **values))
        else:
            connection.execute(
                table.update().where(table.c.id == existing_id).values(**values)
            )


def _seed_role_capabilities(connection: Connection) -> None:
    role_table = Role.__table__
    capability_table = Capability.__table__
    link_table = RoleCapability.__table__
    roles_by_key = {
        row.key: row.id
        for row in connection.execute(
            sa.select(role_table.c.key, role_table.c.id).where(
                role_table.c.workspace_id.is_(None),
                role_table.c.is_system_role.is_(True),
            )
        )
    }
    capabilities_by_key = {
        row.key: row.id
        for row in connection.execute(
            sa.select(capability_table.c.key, capability_table.c.id)
        )
    }

    for role_key, capability_keys in DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS.items():
        role_id = roles_by_key.get(role_key)
        if role_id is None:
            continue
        for capability_key in capability_keys:
            capability_id = capabilities_by_key.get(capability_key)
            if capability_id is None:
                continue
            existing_id = connection.execute(
                sa.select(link_table.c.id).where(
                    link_table.c.role_id == role_id,
                    link_table.c.capability_id == capability_id,
                )
            ).scalar_one_or_none()
            if existing_id is not None:
                continue
            connection.execute(
                link_table.insert().values(
                    id=role_capability_id(role_key, capability_key),
                    role_id=role_id,
                    capability_id=capability_id,
                    source="system_default",
                )
            )
