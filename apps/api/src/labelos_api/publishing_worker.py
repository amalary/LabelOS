"""Private process/job entrypoint: python -m labelos_api.publishing_worker --execute.

Deployment identity and database/IAM permissions authorize this process. There is
no HTTP endpoint, queue-body workspace override, or Scheduling worker principal.
"""

import argparse
import asyncio
import json
import signal
from datetime import timedelta

from labelos_database.session import get_sessionmaker, reset_engine

from labelos_api.config import get_settings
from labelos_api.publishing.registry import publishing_provider_registry
from labelos_api.services.credential_store import build_credential_store
from labelos_api.services.publishing_processor import PublishingProcessor
from labelos_api.social_accounts.providers import (
    social_account_provider_registry_from_settings,
)


def validate_worker_settings(settings):
    if not settings.database_url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("Publishing workers require PostgreSQL with asyncpg")
    if settings.database_echo:
        raise RuntimeError("Publishing worker DATABASE_ECHO must be false")
    if settings.publishing_worker_workspace_id is None:
        raise RuntimeError("PUBLISHING_WORKER_WORKSPACE_ID is required")
    settings.validate_credential_store_backend()
    settings.validate_youtube_oauth_configuration()


async def run_sweep(settings, *, stop=None):
    if not settings.publishing_execution_enabled:
        return {"status": "execution_disabled"}
    validate_worker_settings(settings)
    sessions = get_sessionmaker(settings)
    social_registry = social_account_provider_registry_from_settings(
        youtube_client_id=settings.youtube_oauth_client_id,
        youtube_client_secret=settings.youtube_oauth_client_secret,
        credential_store=build_credential_store(settings),
    )
    processor = PublishingProcessor(
        sessions,
        workspace_id=settings.publishing_worker_workspace_id,
        registry=publishing_provider_registry(
            sessions=sessions, social_account_registry=social_registry
        ),
        batch_size=settings.publishing_worker_batch_size,
        lease_duration=timedelta(seconds=settings.publishing_worker_lease_seconds),
        execution_timeout=settings.publishing_worker_timeout_seconds,
    )
    result = await processor.run(stop=stop)
    return {
        "status": "completed",
        "claimed": result.claimed,
        "recovered": result.recovered,
        "outcomes": dict(result.outcomes),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="One bounded Publishing worker sweep")
    parser.add_argument("--execute", action="store_true", required=True)
    parser.parse_args(argv)

    async def run():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        previous = {}
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(
                signum, lambda *_: loop.call_soon_threadsafe(stop.set)
            )
        try:
            return await run_sweep(get_settings(), stop=stop)
        except Exception:
            return {"status": "failed"}
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            await reset_engine()

    result = asyncio.run(run())
    print(json.dumps(result))
    outcomes = result.get("outcomes")
    return int(
        result["status"] == "failed"
        or (
            isinstance(outcomes, dict)
            and any(outcomes.get(key) for key in ("failed", "timed_out"))
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
