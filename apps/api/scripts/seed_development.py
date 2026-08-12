import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_SRC = ROOT / "apps" / "api" / "src"
DATABASE_SRC = ROOT / "packages" / "database" / "src"
sys.path.insert(0, str(API_SRC))
sys.path.insert(0, str(DATABASE_SRC))

from labelos_database.development_seed import seed_development_workspace  # noqa: E402
from labelos_database.session import get_sessionmaker, reset_engine  # noqa: E402

from labelos_api.config import get_settings  # noqa: E402


async def main() -> None:
    settings = get_settings()
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        summary = await seed_development_workspace(
            settings,
            session,
            environment=settings.environment,
        )

    print(f"Seeded {summary.organization_name} ({summary.organization_id})")
    print(
        "Users: " f"{summary.users_created} created, {summary.users_existing} existing"
    )
    print(
        "Memberships: "
        f"{summary.memberships_created} created, "
        f"{summary.memberships_existing} existing"
    )
    print(
        "Artists: "
        f"{summary.artists_created} created, {summary.artists_existing} existing"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        asyncio.run(reset_engine())
