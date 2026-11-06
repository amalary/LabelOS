"""Run invitation tests on a new, local, disposable PostgreSQL cluster only.

Never reads inherited database/PG settings or starts an existing database.
Usage: python -B apps/api/scripts/invitation_postgres_tests.py <postgres-bin-dir>
Optional following arguments select pytest tests instead of the default suite.
"""

import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    bin_dir = Path(sys.argv[1]).resolve(strict=True)
    targets = sys.argv[2:] or [
        "tests/test_invitation_security.py",
        "tests/test_organizations_api.py",
    ]
    for key in list(os.environ):
        if key.startswith("PG") or key in {"DATABASE_URL", "TEST_POSTGRES_URL"}:
            os.environ.pop(key, None)
    os.environ.update(
        DATABASE_URL="sqlite+aiosqlite://",
        TEST_POSTGRES_URL="",
        APP_ENV="test",
        SCHEDULING_EXECUTION_ENABLED="false",
        PUBLISHING_EXECUTION_ENABLED="false",
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="labelos-invite-test-") as temporary:
        cluster = Path(temporary) / "data"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        def command(executable, *args):
            # A Windows server inherits pipe handles even after pg_ctl exits.
            # Use a file so subprocess cannot wait forever on the live server.
            with (Path(temporary) / "commands.log").open("ab") as log:
                result = subprocess.run(
                    [str(bin_dir / executable), *map(str, args)],
                    stdout=log,
                    stderr=log,
                    creationflags=flags,
                    timeout=60,
                )
            if result.returncode:
                print((Path(temporary) / "commands.log").read_text(errors="replace"))
                result.check_returncode()

        command(
            "initdb.exe",
            "-D",
            cluster,
            "-A",
            "trust",
            "-U",
            "invite_gate",
            "--encoding=UTF8",
            "--locale=C",
        )
        started = False
        try:
            command(
                "pg_ctl.exe",
                "-D",
                cluster,
                "-l",
                Path(temporary) / "postgres.log",
                "-o",
                f"-h 127.0.0.1 -p {port}",
                "-w",
                "-t",
                "30",
                "start",
            )
            started = True
            os.environ["TEST_POSTGRES_URL"] = (
                f"postgresql+asyncpg://invite_gate@127.0.0.1:{port}/postgres"
            )
            # Verify server identity/data directory before allowing test fixtures.
            import psycopg

            with psycopg.connect(
                host="127.0.0.1",
                port=port,
                user="invite_gate",
                dbname="postgres",
                connect_timeout=5,
            ) as connection:
                database, user, directory = connection.execute(
                    "SELECT current_database(), current_user, "
                    "current_setting('data_directory')"
                ).fetchone()
                if (
                    database != "postgres"
                    or user != "invite_gate"
                    or Path(directory).resolve() != cluster.resolve()
                ):
                    raise RuntimeError("Disposable PostgreSQL identity mismatch")
            sys._labelos_disposable_postgres_url = os.environ["TEST_POSTGRES_URL"]
            from sqlalchemy import event
            from sqlalchemy.engine import Engine

            @event.listens_for(Engine, "do_connect")
            def only_disposable_targets(dialect, record, cargs, cparams):
                if dialect.name == "sqlite" and cargs == [":memory:"]:
                    return
                if (
                    dialect.name == "sqlite"
                    and cargs
                    and Path(cargs[0])
                    .resolve()
                    .is_relative_to(Path(temporary).resolve())
                ):
                    return
                if dialect.name == "postgresql" and all(
                    cparams.get(key) == value
                    for key, value in {
                        "host": "127.0.0.1",
                        "port": port,
                        "database": "postgres",
                        "user": "invite_gate",
                    }.items()
                ):
                    return
                raise RuntimeError(
                    "Only the disposable invitation test cluster is allowed"
                )

            import pytest

            os.chdir(Path(__file__).resolve().parents[1])
            return pytest.main(
                [
                    *targets,
                    "-q",
                    "-rs",
                    "-p",
                    "no:cacheprovider",
                    "--tb=short",
                    "--show-capture=no",
                    "--basetemp=" + str(Path(temporary) / "pytest"),
                ]
            )
        finally:
            if started:
                command("pg_ctl.exe", "-D", cluster, "-m", "immediate", "-w", "stop")


if __name__ == "__main__":
    raise SystemExit(main())
