from __future__ import annotations

from uuid import UUID

from labelos_database.models import OrganizationMembership
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.auth import CurrentUserContext


async def has_active_membership(
    session: AsyncSession,
    context: CurrentUserContext,
    organization_id: UUID,
) -> bool:
    membership_id = await session.scalar(
        select(OrganizationMembership.id)
        .where(OrganizationMembership.organization_id == organization_id)
        .where(OrganizationMembership.user_id == context.user.id)
        .where(OrganizationMembership.status == "active")
    )
    return membership_id is not None
