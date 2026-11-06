"""Sweep source references on startup and every minute, without provider calls."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from labelos_database.session import get_sessionmaker

from labelos_api.config import get_settings
from labelos_api.services.scouting_service import purge_sources


@asynccontextmanager
async def scouting_lifespan(app):
    settings = get_settings()
    task = None
    if not settings.is_test:
        maker = get_sessionmaker(settings)

        async def sweep():
            while True:
                try:
                    async with maker() as session:
                        await purge_sources(session)
                        await session.commit()
                except Exception:
                    logging.getLogger(__name__).error("Scouting retention sweep failed")
                await asyncio.sleep(60)

        task = asyncio.create_task(sweep())
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
