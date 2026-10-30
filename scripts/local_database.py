"""Run LabelOS locally with an explicit, isolated database target.

Usage: python scripts/local_database.py status|migrate|api|web|build
Secrets live in the ignored .env.labelos-local file. This launcher never uses an
inherited DATABASE_URL and refuses targets outside the dedicated local database.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def configure():
    profile = dotenv_values(ROOT / ".env.labelos-local", interpolate=False)
    url = profile.get("DATABASE_URL") or ""
    target = urlsplit(url)
    if (
        (target.scheme, target.hostname, target.port, target.path, target.username)
        != ("postgresql+asyncpg", "127.0.0.1", 55432, "/labelos_ar_dev", "labelos")
        or target.query
        or target.fragment
        or not target.password
    ):
        raise RuntimeError("Missing or unsafe isolated LabelOS database profile")
    for key in list(os.environ):
        if key.startswith("PG") or key in ("DATABASE_URL", "COMPOSE_DATABASE_URL"):
            os.environ.pop(key, None)
    # Root application configuration is loaded deliberately, then the database
    # and execution controls are pinned to this local profile.
    for key, value in dotenv_values(ROOT / ".env", interpolate=False).items():
        if (
            value is not None
            and key not in ("DATABASE_URL", "COMPOSE_DATABASE_URL")
            and not key.startswith("PG")
        ):
            os.environ[key] = value
    os.environ.update(
        DATABASE_URL=url,
        APP_ENV="local",
        DATABASE_ECHO="false",
        SCHEDULING_EXECUTION_ENABLED="false",
        PUBLISHING_EXECUTION_ENABLED="false",
        PYTHONDONTWRITEBYTECODE="1",
    )
    source_paths = [str(ROOT / "apps/api/src"), str(ROOT / "packages/database/src")]
    os.environ["PYTHONPATH"] = os.pathsep.join(source_paths)
    for source_path in reversed(source_paths):
        if source_path not in sys.path:
            sys.path.insert(0, source_path)
    return target


def inspect(target):
    with psycopg.connect(
        host="127.0.0.1",
        port=55432,
        dbname="labelos_ar_dev",
        user="labelos",
        password=unquote(target.password),
        connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=10000",
    ) as connection:
        identity = connection.execute(
            "SELECT current_database(), current_user, current_setting('server_version_num')::int"
        ).fetchone()
        if (
            identity[:2] != ("labelos_ar_dev", "labelos")
            or not 180000 <= identity[2] < 190000
        ):
            raise RuntimeError("Unexpected database identity or PostgreSQL version")
        table_count = connection.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
        ).fetchone()[0]
        revision = None
        if connection.execute(
            "SELECT to_regclass('public.alembic_version')"
        ).fetchone()[0]:
            revision = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchall()
        print(
            f"LabelOS: 127.0.0.1:55432/labelos_ar_dev; PostgreSQL {identity[2]}; tables={table_count}; revision={revision}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "migrate", "api", "web", "build"])
    args = parser.parse_args()
    target = configure()
    inspect(target)
    if args.action == "migrate":
        subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "alembic",
                "-c",
                str(ROOT / "packages/database/alembic.ini"),
                "-x",
                "youtube_quota_approved=true",
                "upgrade",
                "head",
            ],
            cwd=ROOT,
            check=True,
        )
        inspect(target)
    elif args.action in {"web", "build"}:
        os.environ.update(
            NODE_ENV="development" if args.action == "web" else "production",
            API_BASE_URL="http://127.0.0.1:4000",
            NEXT_PUBLIC_API_URL="http://127.0.0.1:4000",
            WEB_BASE_URL="http://localhost:3000",
            WORKOS_REDIRECT_URI="http://localhost:3000/api/auth/callback",
            NEXT_PUBLIC_WORKOS_REDIRECT_URI="http://localhost:3000/api/auth/callback",
        )
        command = ["node", str(ROOT / "apps/web/node_modules/next/dist/bin/next")]
        command += (
            ["dev", "--hostname", "127.0.0.1", "--port", "3000"]
            if args.action == "web"
            else ["build"]
        )
        subprocess.run(command, cwd=ROOT / "apps/web", check=True)
    elif args.action == "api":
        subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "uvicorn",
                "labelos_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "4000",
                "--no-access-log",
            ],
            cwd=ROOT / "apps/api",
            check=True,
        )


if __name__ == "__main__":
    try:
        main()
    except (psycopg.Error, RuntimeError, OSError) as error:
        # Connection exceptions can contain connection details; do not print them.
        print(
            f"Local database check failed ({type(error).__name__}); no fallback target was used.",
            file=sys.stderr,
        )
        sys.exit(1)
