"""Synthetic-only Prompt 4 checks. Never load a saved PostgreSQL test target."""

import os
import sys
from pathlib import Path

os.environ["TEST_POSTGRES_URL"] = ""
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["APP_ENV"] = "test"
os.chdir(Path(__file__).resolve().parents[1])

import asyncpg  # noqa: E402
import pytest  # noqa: E402


async def forbidden_postgres(*args, **kwargs):
    raise RuntimeError("This test runner forbids PostgreSQL connections")


asyncpg.connect = forbidden_postgres

if __name__ == "__main__":
    raise SystemExit(
        pytest.main(
            sys.argv[1:]
            or [
                "tests/test_youtube_reliability.py",
                "tests/test_youtube_research_api.py",
                "tests/test_public_music_adapters.py",
                "tests/test_research_providers.py",
                "tests/test_governance.py",
                "tests/test_governance_authorization.py",
                "tests/test_governance_audit.py",
                "tests/test_collection_runs.py",
                "tests/test_analytics_service.py",
                "tests/test_scheduling_processor_migration.py",
                "tests/test_scheduling_persistence.py",
                "tests/test_publishing_persistence.py",
                "-q",
            ]
        )
    )
