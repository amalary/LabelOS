import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from labelos_database.base import Base
from labelos_database.models import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    User,
    WorkspacePermission,
)
from labelos_database.research_models import ScoutingCandidate, ScoutingSource
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from labelos_api.services.scouting_service import purge_sources, save_candidate
from test_analytics_api import _set_context
from test_youtube_research_api import CHANNEL, path, prepare_run
from test_youtube_research_api import configured as configured
from test_youtube_research_api import research_client as research_client


def scout(configured):
    client, maker, seeded, _, _ = configured

    async def grant():
        async with maker() as session:
            member = await session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == seeded.workspace_id,
                    OrganizationMembership.user_id == seeded.analyst_user_id,
                )
            )
            member.workspace_permission = WorkspacePermission.member
            member.role = MembershipRole.member
            member.department_access = ["a&r"]
            member.capability_permissions = ["ar.scouting.view", "ar.scouting.create"]
            await session.commit()

    asyncio.run(grant())
    _set_context(
        client,
        seeded,
        user_id=seeded.analyst_user_id,
        workspace_permission=WorkspacePermission.member,
        department_access=("a&r",),
        capability_permissions=("ar.scouting.view", "ar.scouting.create"),
    )
    return client, maker, seeded, f"/api/v1/workspaces/{seeded.workspace_id}/scouting"


def test_ordinary_ar_workflow_and_persistent_review(configured):
    run, _, _ = prepare_run(configured[0], configured[2])
    client, maker, seeded, base = scout(configured)
    assert client.get(base + "/runs").json()[0]["id"] == run["id"]
    assert (
        client.post(
            path(seeded, run) + "/search", json={"query": "Public", "limit": 2}
        ).status_code
        == 200
    )
    facts = client.post(path(seeded, run) + "/channel", json={"channel_id": CHANNEL})
    assert facts.status_code == 200
    assert len(facts.json()["items"]) == 3
    saved = client.post(base + "/candidates", json={"channel_id": CHANNEL})
    assert saved.status_code == 201, saved.text
    record = saved.json()
    assert "Public channel" not in saved.text and "123" not in record["notes"]
    duplicate = client.post(base + "/candidates", json={"channel_id": CHANNEL})
    assert duplicate.status_code == 200 and duplicate.json()["id"] == record["id"]
    url = base + "/candidates/" + record["id"]
    # New HTTP requests / SQL sessions model a reload, without relying on UI memory.
    assert client.get(url).json() == record
    for notes in ["Listen to the live set", "Live set reviewed; arrange a meeting"]:
        edited = client.patch(
            url,
            json={
                "notes": notes,
                "label": "Human label",
                "status": "shortlisted",
                "revision": record["revision"],
            },
        )
        assert edited.status_code == 200, edited.text
        record = edited.json()
        assert client.get(url).json()["notes"] == notes
    assert len(client.get(base + "/candidates?status=shortlisted").json()) == 1
    assert client.get(base + "/candidates?status=passed").json() == []
    assert (
        client.patch(url, json={"notes": "overwrite", "revision": 1}).status_code == 409
    )
    assert (
        client.patch(
            url, json={"status": "invented", "revision": record["revision"]}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            url, json={"notes": None, "revision": record["revision"]}
        ).status_code
        == 422
    )
    assert client.get(url).headers["cache-control"] == "no-store"
    assert client.delete(url + "/source").status_code == 204
    current = client.get(url).json()
    assert current["channel_id"] is None and current["notes"] == record["notes"]
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_denials_and_workspace_isolation(configured):
    client, _, seeded, base = scout(configured)
    saved = client.post(base + "/candidates", json={"channel_id": CHANNEL}).json()
    foreign = base.replace(str(seeded.workspace_id), str(seeded.outside_workspace_id))
    for method, suffix, body in [
        ("get", "/candidates", None),
        ("get", "/candidates/" + saved["id"], None),
        ("post", "/candidates", {"channel_id": CHANNEL}),
        ("patch", "/candidates/" + saved["id"], {"notes": "attack", "revision": 1}),
        ("delete", "/candidates/" + saved["id"], None),
    ]:
        assert client.request(method, foreign + suffix, json=body).status_code == 403
    assert client.get(base + "/candidates/" + str(uuid4())).status_code == 404
    _set_context(
        client,
        seeded,
        user_id=seeded.analyst_user_id,
        workspace_permission=WorkspacePermission.guest,
        department_access=(),
    )

    # Persisted authority is decisive; revoke the grants in the DB as well.
    async def revoke():
        async with configured[1]() as session:
            row = await session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == seeded.analyst_user_id
                )
            )
            row.capability_permissions = []
            row.department_access = []
            await session.commit()

    asyncio.run(revoke())
    assert client.get(base + "/candidates").status_code == 403
    assert (
        client.post(base + "/candidates", json={"channel_id": CHANNEL}).status_code
        == 403
    )
    client.app.dependency_overrides.clear()
    assert client.get(base + "/candidates").status_code == 401


def test_expired_source_hidden_then_erased_without_changing_review(configured):
    client, maker, _, base = scout(configured)
    record = client.post(base + "/candidates", json={"channel_id": CHANNEL}).json()
    url = base + "/candidates/" + record["id"]
    client.patch(url, json={"notes": "Keep my review", "revision": 1})

    async def expire(purge=False):
        async with maker() as session:
            source = await session.scalar(select(ScoutingSource))
            if not purge:
                source.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            else:
                await purge_sources(session)
            await session.commit()

    asyncio.run(expire())
    assert client.get(url).json()["channel_id"] is None
    asyncio.run(expire(True))
    assert client.get(url).json()["notes"] == "Keep my review"

    async def count():
        async with maker() as session:
            return await session.scalar(
                select(func.count()).select_from(ScoutingSource)
            )

    assert asyncio.run(count()) == 0


def test_concurrent_save_postgres(postgres_test_engine):
    async def run():
        engine = postgres_test_engine
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            owner = User(email="disposable-scout@example.test")
            workspace = Organization(name="Disposable", slug=uuid4().hex, owner=owner)
            session.add(workspace)
            await session.commit()
            workspace_id = workspace.id
        ready = asyncio.Event()

        async def save():
            await ready.wait()
            async with maker() as session:
                result = await save_candidate(session, workspace_id, CHANNEL)
                await session.commit()
                return result

        tasks = [asyncio.create_task(save()) for _ in range(12)]
        ready.set()
        results = await asyncio.gather(*tasks)
        assert len({result[0] for result in results}) == 1
        assert sum(result[1] for result in results) == 1
        async with maker() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(ScoutingCandidate)
                )
                == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(ScoutingSource))
                == 1
            )

    asyncio.run(run())


def test_migrations_and_quota_postgres(postgres_test_engine, monkeypatch):
    from pathlib import Path

    from alembic import context
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from labelos_database.research_models import YouTubeQuotaBucket
    from sqlalchemy import inspect

    from labelos_api.research.errors import AdapterFailure, ProviderErrorCode
    from labelos_api.research.youtube_quota import YouTubeQuota

    scripts = ScriptDirectory.from_config(
        Config(
            str(Path(__file__).resolve().parents[3] / "packages/database/alembic.ini")
        )
    )
    monkeypatch.setattr(
        context, "get_x_argument", lambda **_: {"youtube_quota_approved": "true"}
    )

    def migrate(connection):
        with Operations.context(MigrationContext.configure(connection)):
            for revision in reversed(list(scripts.walk_revisions())):
                revision.module.upgrade()
        tables = inspect(connection).get_table_names()
        assert "scouting_candidates" in tables and "scouting_sources" in tables
        assert len(inspect(connection).get_foreign_keys("scouting_sources")) == 2

    async def run():
        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(migrate)
        sessions = async_sessionmaker(postgres_test_engine)
        now = datetime.now(UTC)
        clients = [
            YouTubeQuota(sessions, spacing=False, clock=lambda: now) for _ in range(2)
        ]
        outcomes = await asyncio.gather(
            *(clients[i % 2].reserve("search") for i in range(90)),
            return_exceptions=True,
        )
        assert sum(result is None for result in outcomes) == 80, [
            str(result) for result in outcomes if result is not None
        ][:3]
        assert all(
            isinstance(result, AdapterFailure)
            and result.details.code == ProviderErrorCode.quota_exceeded
            for result in outcomes
            if result is not None
        )
        async with sessions() as session:
            assert (await session.scalar(select(YouTubeQuotaBucket))).used == 80

    asyncio.run(run())


def test_concurrent_http_saves_postgres(postgres_test_engine):
    from types import SimpleNamespace

    import httpx
    from labelos_database.models import UniversalProfile, WorkspaceMembership

    from labelos_api.auth import get_session
    from labelos_api.main import create_app

    async def run():
        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(postgres_test_engine, expire_on_commit=False)
        async with maker() as session:
            user = User(email="scout-http@example.test")
            workspace = Organization(
                name="Disposable HTTP",
                slug=uuid4().hex,
                owner=user,
                workos_organization_id="org_ALPHA_ANALYTICS",
            )
            membership = OrganizationMembership(
                organization=workspace,
                user=user,
                role=MembershipRole.member,
                workspace_permission=WorkspacePermission.member,
                department_access=["a&r"],
                capability_permissions=["ar.scouting.view", "ar.scouting.create"],
            )
            profile = UniversalProfile(
                user=user, slug=uuid4().hex, display_name="Disposable scout"
            )
            session.add(
                WorkspaceMembership(
                    workspace=workspace,
                    profile=profile,
                    organization_membership=membership,
                    status="active",
                )
            )
            await session.commit()
            workspace_id, user_id = workspace.id, user.id
        app = create_app()

        async def sessions():
            async with maker() as session:
                yield session

        app.dependency_overrides[get_session] = sessions
        _set_context(
            SimpleNamespace(app=app),
            SimpleNamespace(owner_user_id=user_id, workspace_id=workspace_id),
            workspace_permission=WorkspacePermission.member,
            department_access=("a&r",),
            capability_permissions=("ar.scouting.view", "ar.scouting.create"),
        )
        base = f"/api/v1/workspaces/{workspace_id}/scouting/candidates"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://disposable.test"
        ) as client:
            results = await asyncio.gather(
                *(client.post(base, json={"channel_id": CHANNEL}) for _ in range(12))
            )
            assert sorted(response.status_code for response in results) == [
                200
            ] * 11 + [201]
            assert len({response.json()["id"] for response in results}) == 1
            candidate_id = results[0].json()["id"]
            edited = await client.patch(
                base + "/" + candidate_id,
                json={
                    "notes": "Persist across requests",
                    "status": "reviewing",
                    "revision": 1,
                },
            )
            assert edited.status_code == 200
            reopened = await client.get(base + "/" + candidate_id)
            assert reopened.json()["notes"] == "Persist across requests"
            assert len((await client.get(base)).json()) == 1

    asyncio.run(run())


def test_foreign_candidate_id_hidden_even_in_authorized_workspace(configured):
    client, maker, seeded, base = scout(configured)

    async def create_foreign():
        async with maker() as session:
            candidate_id, _ = await save_candidate(
                session, seeded.outside_workspace_id, CHANNEL
            )
            await session.commit()
            return candidate_id

    candidate_id = asyncio.run(create_foreign())
    assert client.get(base + "/candidates/" + str(candidate_id)).status_code == 404
    own = client.post(base + "/candidates", json={"channel_id": CHANNEL})
    assert own.status_code == 201 and own.json()["id"] != str(candidate_id)
    assert len(client.get(base + "/candidates").json()) == 1


def test_deleted_channel_erases_source_and_keeps_review(configured, monkeypatch):
    import httpx

    from labelos_api.research.adapters.youtube import YouTubeAdapter
    from test_youtube_research_api import service

    run, _, _ = prepare_run(configured[0], configured[2])
    client, _, seeded, base = scout(configured)
    record = client.post(base + "/candidates", json={"channel_id": CHANNEL}).json()
    detail = base + "/candidates/" + record["id"]
    client.patch(detail, json={"notes": "Human opinion", "revision": 1})
    monkeypatch.setattr(
        service,
        "YouTubeAdapter",
        lambda: YouTubeAdapter(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"items": []})
            )
        ),
    )
    assert (
        client.post(
            path(seeded, run) + "/channel", json={"channel_id": CHANNEL}
        ).status_code
        == 404
    )
    current = client.get(detail).json()
    assert current["channel_id"] is None and current["notes"] == "Human opinion"
