"""Explicit local smoke checks. No test fixtures, account creation, or secret output.

Usage: python -B scripts/validate_local_workflow.py http|schema|youtube
The youtube action spends one bounded search and one channel request (plus at
most one bounded channel retry). It uses the guarded local quota ledger.
"""

import argparse
import asyncio
import os
import subprocess
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import local_database


def http_check():
    import httpx

    with httpx.Client(timeout=45, trust_env=False, follow_redirects=False) as client:
        for path in ("/health", "/health/database", "/api/v1/me"):
            response = client.get("http://127.0.0.1:4000" + path)
            print("API", path, response.status_code)
            assert response.status_code == (401 if path == "/api/v1/me" else 200)
        for path in ("/login", "/api/auth/login", "/scouting"):
            response = client.get("http://localhost:3000" + path)
            redirect = urlsplit(response.headers.get("location", ""))
            print(
                "WEB",
                path,
                response.status_code,
                "redirect_host=",
                redirect.hostname,
                "callback=",
                parse_qs(redirect.query).get("redirect_uri"),
            )
            assert response.status_code == (200 if path == "/login" else 307)
            if path != "/login":
                assert redirect.hostname == "api.workos.com"
                assert parse_qs(redirect.query).get("redirect_uri") == [
                    "http://localhost:3000/api/auth/callback"
                ]
            if path == "/api/auth/login" and redirect.hostname == "api.workos.com":
                hosted = client.get(response.headers["location"], follow_redirects=True)
                print(
                    "WorkOS hosted login",
                    hosted.status_code,
                    "form_present=",
                    "<form" in hosted.text,
                )
                assert hosted.status_code == 200 and "<form" in hosted.text


def schema_check():
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from labelos_database import models  # noqa: F401
    from labelos_database.base import Base
    from sqlalchemy import create_engine, text

    scripts = ScriptDirectory.from_config(
        Config(str(local_database.ROOT / "packages/database/alembic.ini"))
    )
    engine = create_engine(
        os.environ["DATABASE_URL"].replace(
            "postgresql+asyncpg:", "postgresql+psycopg:"
        ),
        connect_args={
            "options": "-c default_transaction_read_only=on -c statement_timeout=20000",
            "connect_timeout": 5,
        },
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("select current_database(), current_user")
        ).one() == ("labelos_ar_dev", "labelos")
        print("repository_heads=", scripts.get_heads())
        differences = compare_metadata(
            MigrationContext.configure(connection), Base.metadata
        )
        print("schema_difference_count=", len(differences))
        assert not differences
        assert (
            connection.execute(text("select version_num from alembic_version")).scalar()
            == scripts.get_current_head()
        )
        for name in (
            "users",
            "organizations",
            "collection_runs",
            "scouting_candidates",
            "scouting_sources",
        ):
            print(
                name,
                "rows=",
                connection.execute(text("select count(*) from " + name)).scalar(),
            )
        print("UI_enabled=", os.environ.get("YOUTUBE_RESEARCH_UI_ENABLED") == "true")
        print(
            "reviewed_local_policies_configured=",
            os.environ.get("APP_ENV") == "local"
            and os.environ.get("YOUTUBE_RESEARCH_USE_LOCAL_POLICIES") == "true"
            and os.environ.get("LABELOS_RESEARCH_POLICIES_APPROVED") == "true"
            and bool(os.environ.get("LABELOS_POLICY_OPERATOR"))
            and bool(os.environ.get("LABELOS_PRIVACY_CONTACT")),
        )
        for name in (
            "YOUTUBE_RESEARCH_PRIVACY_POLICY_URL",
            "YOUTUBE_RESEARCH_TERMS_URL",
        ):
            print(
                name,
                "configured_https=",
                os.environ.get(name, "").startswith("https://"),
            )
    engine.dispose()


def secrets_check():
    import re

    from dotenv import dotenv_values

    values = []
    secret_names = {}
    for filename in (".env", "apps/web/.env.local"):
        profile = dotenv_values(local_database.ROOT / filename, interpolate=False)
        for key in (
            "WORKOS_API_KEY",
            "WORKOS_COOKIE_PASSWORD",
            "WORKOS_WEBHOOK_SECRET",
        ):
            value = profile.get(key)
            if value and len(value) >= 12:
                values.append(value.encode())
                secret_names[value.encode()] = key
    diff = subprocess.run(
        ["git", "diff", "--no-ext-diff"],
        cwd=local_database.ROOT,
        capture_output=True,
        check=True,
    ).stdout
    browser_paths = list((local_database.ROOT / "apps/web/.next/static").rglob("*.js"))
    source_names = (
        subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=local_database.ROOT,
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .split("\0")
    )
    source_paths = [
        local_database.ROOT / name
        for name in source_names
        if name and (local_database.ROOT / name).is_file()
    ]
    log_paths = list((local_database.ROOT / ".runlogs").rglob("*.log"))
    paths = list(dict.fromkeys(browser_paths + source_paths + log_paths))
    assert browser_paths and values
    hits = int(any(value in diff for value in values))
    for path in paths:
        content = path.read_bytes()
        matched = any(value in content for value in values)
        hits += int(matched)
        if matched:
            print(
                "Secret match file (value suppressed):",
                path.relative_to(local_database.ROOT),
                "keys=",
                [secret_names[value] for value in values if value in content],
            )
    print(
        "Known configured WorkOS secret matches in diff/source/browser JS/local logs=",
        hits,
        "browser_js_files_scanned=",
        len(browser_paths),
        "source_files_scanned=",
        len(source_paths),
        "local_logs_scanned=",
        len(log_paths),
    )
    if hits:
        raise RuntimeError("Secret scan failed")
    restricted = re.compile(
        rb'AIza[A-Za-z0-9_-]{35}|Bearer\s+[A-Za-z0-9_.-]{20,}|["\x27](?:subscriberCount|viewCount|videoCount)["\x27]\s*:'
        rb"|[?&]code=[A-Za-z0-9_.-]{10,}|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}"
        rb"|/(?:join|invites)/[A-Za-z0-9_-]{20,}"
    )
    log_hits = sum(bool(restricted.search(path.read_bytes())) for path in log_paths)
    print("Provider key/token/raw-counter payload pattern log matches=", log_hits)
    if log_hits:
        raise RuntimeError("Restricted log payload scan failed")


async def youtube_check():
    from dataclasses import replace

    from labelos_api.config import get_settings
    from labelos_api.research.adapters.youtube import YouTubeAdapter
    from labelos_api.research.contracts import (
        ArtistLookupRequest,
        ArtistSearchRequest,
        CollectionContext,
        ProviderConfiguration,
    )
    from labelos_api.research.errors import ProviderError
    from labelos_api.research.providers import ProviderClient
    from labelos_api.research.youtube_quota import YouTubeQuota
    from labelos_api.services.credential_store import build_credential_store
    from labelos_database.session import get_sessionmaker, reset_engine

    settings = get_settings()
    settings.validate_youtube_research_configuration()
    reference = settings.youtube_research_local_credential_ref
    if not reference:
        print("BLOCKED: no configured local YouTube credential reference")
        return
    store = build_credential_store(settings)
    original = store.client

    class BoundedSecretRead:
        def access_secret_version(self, *, request):
            return original.access_secret_version(
                request=request, retry=None, timeout=10
            )

    store = replace(store, client=BoundedSecretRead())
    workspace, provider, run, version = [uuid4() for _ in range(4)]
    context = CollectionContext(
        workspace_id=workspace,
        provider_id=provider,
        provider_key="youtube",
        collection_run_id=run,
        dataset_version_id=version,
    )
    adapter = YouTubeAdapter()
    adapter.quota = YouTubeQuota(get_sessionmaker(settings))
    client = ProviderClient(
        adapter,
        ProviderConfiguration(
            workspace_id=workspace,
            provider_id=provider,
            provider_key="youtube",
            credential_ref=reference,
            timeout_seconds=20,
        ),
        credential_store=store,
    )
    try:
        lookup = await client.lookup_artist(
            ArtistLookupRequest(artist_id="UC_x5XG1OV2P6uZZ5FSM9Ttw"), context=context
        )
        print(
            "LIVE lookup: passed; channel_id_matches=",
            lookup.artist.external_id == "UC_x5XG1OV2P6uZZ5FSM9Ttw",
            "expiry_present=",
            bool(lookup.artist.provenance.expires_at),
        )
        result = await client.search_artists(
            ArtistSearchRequest(query="Google for Developers", limit=3), context=context
        )
        assert len(result.items) <= 3
        print(
            "LIVE bounded search: passed; returned=",
            len(result.items),
            "limit=3; pagination_not_followed=True",
        )
        print(
            "Diagnostic adapter path only; no authenticated workspace/run claimed. No provider content persisted."
        )
    except ProviderError as error:
        print("LIVE YouTube failure:", error.failure.details.code.value)
        raise SystemExit(1) from None
    finally:
        await reset_engine()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("http", "schema", "youtube", "secrets"))
    action = parser.parse_args().action
    target = local_database.configure()
    local_database.inspect(target)
    if action == "http":
        http_check()
    elif action == "schema":
        schema_check()
    elif action == "secrets":
        secrets_check()
    else:
        asyncio.run(youtube_check())


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - never print credential diagnostics
        print(f"Local verification failed ({type(error).__name__}); details suppressed")
        raise SystemExit(1) from None
