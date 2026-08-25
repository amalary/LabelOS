import asyncio

import pytest
from labelos_database import Base
from labelos_database.models import (
    ProfileAttribute,
    ProfileLink,
    ProfilePreference,
    UniversalProfile,
    User,
)
from labelos_database.profile_metadata import (
    create_profile_attribute,
    create_profile_link,
    delete_profile_attribute,
    delete_profile_link,
    delete_profile_preference,
    list_profile_attributes,
    list_profile_links,
    upsert_profile_preference,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def _seed_profile(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> UniversalProfile:
    async with sessionmaker() as session:
        profile = UniversalProfile(
            user=User(email="metadata@example.com", workos_user_id="user_metadata"),
            display_name="Metadata User",
            slug="metadata-user",
        )
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
        return profile


def test_profile_metadata_crud_helpers_manage_profile_extensions() -> None:
    async def run() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        profile = await _seed_profile(sessionmaker)
        async with sessionmaker() as session:
            title = await create_profile_attribute(
                session,
                profile.id,
                attribute_type="professional_title",
                label="Professional title",
                value="Label Manager",
                is_primary=True,
            )
            await create_profile_attribute(
                session,
                profile.id,
                attribute_type="instrument",
                value="Piano",
                sort_order=2,
                metadata={"proficiency": "advanced"},
            )

            titles = await list_profile_attributes(
                session,
                profile.id,
                attribute_type="professional_title",
            )
            assert titles == [title]

            link = await create_profile_link(
                session,
                profile.id,
                link_type="spotify",
                label="Spotify",
                url="https://open.spotify.com/artist/example",
                username="example-artist",
                external_id="spotify:artist:example",
                metadata={"followers": 1000},
            )
            links = await list_profile_links(session, profile.id, link_type="spotify")
            assert links == [link]

            preference = await upsert_profile_preference(
                session,
                profile.id,
                locale="en-US",
                timezone="America/Los_Angeles",
                interface_theme="system",
                notification_preferences={"digest": "weekly"},
            )
            updated_preference = await upsert_profile_preference(
                session,
                profile.id,
                push_notifications_enabled=False,
                interface_density="compact",
            )

            assert preference.id == updated_preference.id
            assert updated_preference.locale == "en-US"
            assert updated_preference.push_notifications_enabled is False
            assert updated_preference.interface_density == "compact"
            assert await delete_profile_attribute(session, profile.id, title.id) is True
            assert await delete_profile_link(session, profile.id, link.id) is True
            assert await delete_profile_preference(session, profile.id) is True

        await engine.dispose()

    asyncio.run(run())


def test_profile_metadata_validation_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="attribute_type is required"):
        ProfileAttribute(attribute_type=" ", value="Producer")

    with pytest.raises(ValueError, match="absolute HTTP"):
        ProfileLink(link_type="website", url="not-a-url")

    with pytest.raises(ValueError, match="JSON object"):
        ProfileLink(link_type="spotify", url="https://example.com", metadata_json=[])

    with pytest.raises(ValueError, match="locale"):
        ProfilePreference(locale="not a locale")
