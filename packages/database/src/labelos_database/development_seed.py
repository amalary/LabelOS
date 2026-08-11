from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_database.config import DatabaseSettings
from labelos_database.models import (
    Artist,
    MembershipRole,
    Organization,
    OrganizationMembership,
    User,
)

DEVELOPMENT_ENVIRONMENTS = {"local", "development", "dev", "test"}
LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}

MALARY_WORKOS_ORGANIZATION_ID = "dev_seed_org_malary_records"
MALARY_ORGANIZATION_SLUG = "dev-malary-records"


@dataclass(frozen=True)
class SeedUser:
    workos_user_id: str
    email: str
    first_name: str
    last_name: str
    display_name: str
    role: MembershipRole
    workos_membership_id: str


@dataclass(frozen=True)
class DevelopmentSeedSummary:
    organization_id: str
    organization_name: str
    users_created: int
    users_existing: int
    memberships_created: int
    memberships_existing: int
    artists_created: int
    artists_existing: int


MALARY_USERS = (
    SeedUser(
        workos_user_id="dev_seed_user_malary_owner",
        email="owner+dev-seed@malary-records.example.test",
        first_name="Mara",
        last_name="Vale",
        display_name="Mara Vale (Dev Owner)",
        role=MembershipRole.owner,
        workos_membership_id="dev_seed_membership_malary_owner",
    ),
    SeedUser(
        workos_user_id="dev_seed_user_malary_admin",
        email="admin+dev-seed@malary-records.example.test",
        first_name="Inez",
        last_name="Park",
        display_name="Inez Park (Dev Admin)",
        role=MembershipRole.admin,
        workos_membership_id="dev_seed_membership_malary_admin",
    ),
    SeedUser(
        workos_user_id="dev_seed_user_malary_member",
        email="member+dev-seed@malary-records.example.test",
        first_name="Theo",
        last_name="King",
        display_name="Theo King (Dev Member)",
        role=MembershipRole.member,
        workos_membership_id="dev_seed_membership_malary_member",
    ),
)

MALARY_ARTISTS = (
    "Nia Calder",
    "The Harbor Lights",
    "Juniper Knox",
    "Vega North",
    "Milo Reyes",
)


def validate_development_seed_environment(
    *,
    environment: str,
    database_url: str,
) -> None:
    normalized_environment = environment.lower()
    if normalized_environment not in DEVELOPMENT_ENVIRONMENTS:
        raise RuntimeError(
            "Development seed is disabled outside local/development/test "
            f"environments. APP_ENV={environment!r}."
        )

    url = make_url(database_url)
    if url.drivername.startswith("sqlite"):
        return
    if url.host not in LOCAL_DATABASE_HOSTS:
        raise RuntimeError(
            "Development seed only runs against local SQLite or localhost PostgreSQL "
            "database URLs."
        )


async def seed_malary_records_workspace(
    session: AsyncSession,
) -> DevelopmentSeedSummary:
    users_created = 0
    users_existing = 0
    memberships_created = 0
    memberships_existing = 0
    artists_created = 0
    artists_existing = 0

    users_by_workos_id: dict[str, User] = {}
    for seed_user in MALARY_USERS:
        user = await session.scalar(
            select(User).where(User.workos_user_id == seed_user.workos_user_id)
        )
        if user is None:
            user = User(
                workos_user_id=seed_user.workos_user_id,
                email=seed_user.email,
                first_name=seed_user.first_name,
                last_name=seed_user.last_name,
                display_name=seed_user.display_name,
            )
            session.add(user)
            users_created += 1
        else:
            user.email = seed_user.email
            user.first_name = seed_user.first_name
            user.last_name = seed_user.last_name
            user.display_name = seed_user.display_name
            users_existing += 1
        users_by_workos_id[seed_user.workos_user_id] = user

    await session.flush()
    owner = users_by_workos_id["dev_seed_user_malary_owner"]

    organization = await session.scalar(
        select(Organization).where(
            Organization.workos_organization_id == MALARY_WORKOS_ORGANIZATION_ID
        )
    )
    if organization is None:
        organization = Organization(
            name="Malary Records",
            slug=MALARY_ORGANIZATION_SLUG,
            workos_organization_id=MALARY_WORKOS_ORGANIZATION_ID,
            owner_user_id=owner.id,
        )
        session.add(organization)
    else:
        organization.name = "Malary Records"
        organization.slug = MALARY_ORGANIZATION_SLUG
        organization.owner_user_id = owner.id

    await session.flush()

    for seed_user in MALARY_USERS:
        user = users_by_workos_id[seed_user.workos_user_id]
        membership = await session.scalar(
            select(OrganizationMembership)
            .where(OrganizationMembership.organization_id == organization.id)
            .where(OrganizationMembership.user_id == user.id)
        )
        if membership is None:
            membership = OrganizationMembership(
                workos_membership_id=seed_user.workos_membership_id,
                organization_id=organization.id,
                user_id=user.id,
                role=seed_user.role,
                status="active",
            )
            session.add(membership)
            memberships_created += 1
        else:
            membership.workos_membership_id = seed_user.workos_membership_id
            membership.role = seed_user.role
            membership.status = "active"
            memberships_existing += 1

    for artist_name in MALARY_ARTISTS:
        artist = await session.scalar(
            select(Artist)
            .where(Artist.organization_id == organization.id)
            .where(func.lower(Artist.name) == artist_name.lower())
        )
        if artist is None:
            session.add(Artist(organization_id=organization.id, name=artist_name))
            artists_created += 1
        else:
            artist.name = artist_name
            artists_existing += 1

    await session.commit()
    await session.refresh(organization)

    return DevelopmentSeedSummary(
        organization_id=str(organization.id),
        organization_name=organization.name,
        users_created=users_created,
        users_existing=users_existing,
        memberships_created=memberships_created,
        memberships_existing=memberships_existing,
        artists_created=artists_created,
        artists_existing=artists_existing,
    )


async def seed_development_workspace(
    settings: DatabaseSettings,
    session: AsyncSession,
    *,
    environment: str,
) -> DevelopmentSeedSummary:
    validate_development_seed_environment(
        environment=environment,
        database_url=settings.database_url,
    )
    return await seed_malary_records_workspace(session)
