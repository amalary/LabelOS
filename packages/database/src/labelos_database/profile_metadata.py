from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_database.models import ProfileAttribute, ProfileLink, ProfilePreference


async def list_profile_attributes(
    session: AsyncSession,
    profile_id: UUID,
    *,
    attribute_type: str | None = None,
) -> list[ProfileAttribute]:
    statement = select(ProfileAttribute).where(
        ProfileAttribute.profile_id == profile_id
    )
    if attribute_type is not None:
        statement = statement.where(ProfileAttribute.attribute_type == attribute_type)
    rows = await session.scalars(
        statement.order_by(
            ProfileAttribute.sort_order,
            ProfileAttribute.attribute_type,
            ProfileAttribute.created_at,
            ProfileAttribute.id,
        )
    )
    return list(rows.all())


async def get_profile_attribute(
    session: AsyncSession,
    profile_id: UUID,
    attribute_id: UUID,
) -> ProfileAttribute | None:
    return await session.scalar(
        select(ProfileAttribute)
        .where(ProfileAttribute.profile_id == profile_id)
        .where(ProfileAttribute.id == attribute_id)
    )


async def create_profile_attribute(
    session: AsyncSession,
    profile_id: UUID,
    *,
    attribute_type: str,
    value: str,
    label: str | None = None,
    source: str = "user",
    is_primary: bool = False,
    sort_order: int = 0,
    metadata: dict | None = None,
) -> ProfileAttribute:
    attribute = ProfileAttribute(
        profile_id=profile_id,
        attribute_type=attribute_type,
        label=label,
        value=value,
        source=source,
        is_primary=is_primary,
        sort_order=sort_order,
        metadata_json=metadata,
    )
    session.add(attribute)
    await session.commit()
    await session.refresh(attribute)
    return attribute


async def update_profile_attribute(
    session: AsyncSession,
    profile_id: UUID,
    attribute_id: UUID,
    **changes: object,
) -> ProfileAttribute | None:
    attribute = await get_profile_attribute(session, profile_id, attribute_id)
    if attribute is None:
        return None
    if "metadata" in changes:
        changes["metadata_json"] = changes.pop("metadata")
    for key, value in changes.items():
        setattr(attribute, key, value)
    await session.commit()
    await session.refresh(attribute)
    return attribute


async def delete_profile_attribute(
    session: AsyncSession,
    profile_id: UUID,
    attribute_id: UUID,
) -> bool:
    attribute = await get_profile_attribute(session, profile_id, attribute_id)
    if attribute is None:
        return False
    await session.delete(attribute)
    await session.commit()
    return True


async def list_profile_links(
    session: AsyncSession,
    profile_id: UUID,
    *,
    link_type: str | None = None,
) -> list[ProfileLink]:
    statement = select(ProfileLink).where(ProfileLink.profile_id == profile_id)
    if link_type is not None:
        statement = statement.where(ProfileLink.link_type == link_type)
    rows = await session.scalars(
        statement.order_by(
            ProfileLink.sort_order,
            ProfileLink.link_type,
            ProfileLink.created_at,
            ProfileLink.id,
        )
    )
    return list(rows.all())


async def get_profile_link(
    session: AsyncSession,
    profile_id: UUID,
    link_id: UUID,
) -> ProfileLink | None:
    return await session.scalar(
        select(ProfileLink)
        .where(ProfileLink.profile_id == profile_id)
        .where(ProfileLink.id == link_id)
    )


async def create_profile_link(
    session: AsyncSession,
    profile_id: UUID,
    *,
    link_type: str,
    url: str,
    label: str | None = None,
    username: str | None = None,
    external_id: str | None = None,
    status: str = "active",
    is_primary: bool = False,
    sort_order: int = 0,
    metadata: dict | None = None,
) -> ProfileLink:
    link = ProfileLink(
        profile_id=profile_id,
        link_type=link_type,
        label=label,
        url=url,
        username=username,
        external_id=external_id,
        status=status,
        is_primary=is_primary,
        sort_order=sort_order,
        metadata_json=metadata,
    )
    session.add(link)
    await session.commit()
    await session.refresh(link)
    return link


async def update_profile_link(
    session: AsyncSession,
    profile_id: UUID,
    link_id: UUID,
    **changes: object,
) -> ProfileLink | None:
    link = await get_profile_link(session, profile_id, link_id)
    if link is None:
        return None
    if "metadata" in changes:
        changes["metadata_json"] = changes.pop("metadata")
    for key, value in changes.items():
        setattr(link, key, value)
    await session.commit()
    await session.refresh(link)
    return link


async def delete_profile_link(
    session: AsyncSession,
    profile_id: UUID,
    link_id: UUID,
) -> bool:
    link = await get_profile_link(session, profile_id, link_id)
    if link is None:
        return False
    await session.delete(link)
    await session.commit()
    return True


async def get_profile_preference(
    session: AsyncSession,
    profile_id: UUID,
) -> ProfilePreference | None:
    return await session.scalar(
        select(ProfilePreference).where(ProfilePreference.profile_id == profile_id)
    )


async def upsert_profile_preference(
    session: AsyncSession,
    profile_id: UUID,
    **changes: object,
) -> ProfilePreference:
    preference = await get_profile_preference(session, profile_id)
    if preference is None:
        preference = ProfilePreference(profile_id=profile_id)
        session.add(preference)
    for key, value in changes.items():
        setattr(preference, key, value)
    await session.commit()
    await session.refresh(preference)
    return preference


async def delete_profile_preference(
    session: AsyncSession,
    profile_id: UUID,
) -> bool:
    preference = await get_profile_preference(session, profile_id)
    if preference is None:
        return False
    await session.delete(preference)
    await session.commit()
    return True
