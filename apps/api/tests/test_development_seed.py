import asyncio
from collections.abc import Iterator

import pytest
from labelos_database.base import Base
from labelos_database.config import DatabaseSettings
from labelos_database.development_seed import (
    MALARY_ARTISTS,
    MALARY_USERS,
    seed_development_workspace,
    validate_development_seed_environment,
)
from labelos_database.models import Artist, Organization, OrganizationMembership, User
from labelos_database.session import get_engine, get_sessionmaker, reset_engine
from sqlalchemy import func, select


@pytest.fixture
def seed_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> Iterator[DatabaseSettings]:
    monkeypatch.setenv("APP_ENV", "test")
    database_path = tmp_path / "seed.sqlite3"
    settings = DatabaseSettings(database_url=f"sqlite+aiosqlite:///{database_path}")

    async def prepare_database() -> None:
        async with get_engine(settings).begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())
    yield settings
    asyncio.run(reset_engine())


async def _run_seed(settings: DatabaseSettings) -> tuple:
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        summary = await seed_development_workspace(
            settings,
            session,
            environment="test",
        )
        organization = await session.scalar(
            select(Organization).where(Organization.name == "Malary Records")
        )
        users = (await session.scalars(select(User))).all()
        memberships = (await session.scalars(select(OrganizationMembership))).all()
        artists = (await session.scalars(select(Artist))).all()
        return summary, organization, users, memberships, artists


async def _seed_twice(settings: DatabaseSettings) -> tuple:
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        first_summary = await seed_development_workspace(
            settings,
            session,
            environment="test",
        )
        second_summary = await seed_development_workspace(
            settings,
            session,
            environment="test",
        )
        users_count = await session.scalar(select(func.count()).select_from(User))
        memberships_count = await session.scalar(
            select(func.count()).select_from(OrganizationMembership)
        )
        artists_count = await session.scalar(select(func.count()).select_from(Artist))
        return (
            first_summary,
            second_summary,
            users_count,
            memberships_count,
            artists_count,
        )


def test_development_seed_creates_malary_records(
    seed_settings: DatabaseSettings,
) -> None:
    summary, organization, users, memberships, artists = asyncio.run(
        _run_seed(seed_settings)
    )

    assert organization is not None
    assert summary.users_created == len(MALARY_USERS)
    assert summary.memberships_created == len(MALARY_USERS)
    assert summary.artists_created == len(MALARY_ARTISTS)
    assert len(users) == len(MALARY_USERS)
    assert len(memberships) == len(MALARY_USERS)
    assert len(artists) == len(MALARY_ARTISTS)
    assert {user.email for user in users} == {seed.email for seed in MALARY_USERS}
    assert all("dev-seed" in user.email for user in users)


def test_development_seed_is_idempotent(seed_settings: DatabaseSettings) -> None:
    (
        first_summary,
        second_summary,
        users_count,
        memberships_count,
        artists_count,
    ) = asyncio.run(_seed_twice(seed_settings))

    assert first_summary.users_created == len(MALARY_USERS)
    assert second_summary.users_created == 0
    assert second_summary.users_existing == len(MALARY_USERS)
    assert second_summary.memberships_created == 0
    assert second_summary.artists_created == 0
    assert users_count == len(MALARY_USERS)
    assert memberships_count == len(MALARY_USERS)
    assert artists_count == len(MALARY_ARTISTS)


def test_development_seed_rejects_production_environment() -> None:
    with pytest.raises(RuntimeError, match="disabled outside"):
        validate_development_seed_environment(
            environment="production",
            database_url="postgresql+asyncpg://localhost/labelos",
        )


def test_development_seed_rejects_remote_database_url() -> None:
    with pytest.raises(RuntimeError, match="local SQLite or localhost PostgreSQL"):
        validate_development_seed_environment(
            environment="development",
            database_url="postgresql+asyncpg://labelos:password@prod.example.com/labelos",
        )
