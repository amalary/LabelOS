"""Run the onboarding security gate without access to a persistent database.

Usage (from any directory): apps/api/.venv/Scripts/python.exe -B
    apps/api/scripts/security_gate_tests.py
Optional arguments select pytest tests instead of the default focused suite.
"""

import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    # Set these in the pytest process: Windows drops empty variables when spawning
    # a child, which would let conftest reload TEST_POSTGRES_URL from a dotenv file.
    os.environ.update(
        DATABASE_URL="sqlite+aiosqlite://",
        TEST_POSTGRES_URL="",
        APP_ENV="test",
        SCHEDULING_EXECUTION_ENABLED="false",
        PUBLISHING_EXECUTION_ENABLED="false",
    )
    import asyncpg
    import pytest
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    temporary = tempfile.TemporaryDirectory(prefix="labelos-security-tests-")
    test_root = Path(temporary.name).resolve()

    @event.listens_for(Engine, "do_connect")
    def only_disposable_sqlite(dialect, connection_record, cargs, cparams):
        if dialect.name == "sqlite" and (
            cargs[0] == ":memory:" or Path(cargs[0]).resolve().is_relative_to(test_root)
        ):
            return
        raise RuntimeError("Security gate permits only its disposable SQLite databases")

    async def refuse_postgres(*args, **kwargs):
        raise RuntimeError("PostgreSQL connections disabled for security gate")

    asyncpg.connect = refuse_postgres
    os.chdir(Path(__file__).resolve().parents[1])
    suites = [
        "onboarding_security",
        "invitation_security",
        "dashboard_api",
        "organizations_api",
        "auth",
        "authorization_service",
        "authorization_guards",
        "authorization_permission_matrix",
        "workspace_memberships",
        "organization_isolation",
        "profiles_api",
        "workos_webhooks",
        "governance_authorization",
        "youtube_research_api",
    ]
    targets = sys.argv[1:] or [f"tests/test_{suite}.py" for suite in suites]
    try:
        return pytest.main(
            [
                *targets,
                "--basetemp",
                str(test_root / "pytest"),
                "-q",
                "-rs",
                "-p",
                "no:cacheprovider",
                "--tb=short",
                "--show-capture=no",
            ]
        )
    finally:
        temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
