"""First-login dashboard requests use real disposable database sessions."""

import asyncio

import httpx
from labelos_database.base import Base
from labelos_database.models import AuthIdentity, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from labelos_api import auth
from labelos_api.main import create_app


def principal():
    return auth.AuthenticatedPrincipal(
        provider="workos",
        subject="user_first_login_test",
        session_id="session_first_login_test",
        email="first-login@example.test",
        display_name="New user",
        organization_id=None,
    )


def test_first_login_lists_no_workspaces_and_reloads_identity(database_test_engine):
    async def run():
        async with database_test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(database_test_engine, expire_on_commit=False)
        app = create_app()

        async def sessions():
            async with maker() as session:
                yield session

        app.dependency_overrides[auth.get_session] = sessions
        app.dependency_overrides[auth.get_current_principal] = principal
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            for _ in range(2):
                response = await client.get("/api/v1/organizations?limit=100")
                assert response.status_code == 200
                assert response.json()["organizations"] == []
                assert response.json()["total"] == 0
            assert (
                await client.get("/api/v1/organizations/current")
            ).status_code == 403
            assert (await client.get("/api/v1/profiles/me")).status_code == 200
        async with maker() as session:
            assert await session.scalar(select(func.count()).select_from(User)) == 1
            assert (
                await session.scalar(select(func.count()).select_from(AuthIdentity))
                == 1
            )

    asyncio.run(run())


def test_parallel_first_dashboard_requests_postgres(postgres_test_engine, monkeypatch):
    async def run():
        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(postgres_test_engine, expire_on_commit=False)
        app = create_app()

        async def sessions():
            async with maker() as session:
                yield session

        # Make all three dashboard requests observe a missing identity before
        # any insert, so both the successful creation and conflict paths run.
        original_load = auth._load_auth_identity
        gate = asyncio.Event()
        arrivals = 0

        async def load(session, actor):
            nonlocal arrivals
            identity = await original_load(session, actor)
            if identity is None and arrivals < 3:
                arrivals += 1
                if arrivals == 3:
                    gate.set()
                await asyncio.wait_for(gate.wait(), timeout=10)
            return identity

        monkeypatch.setattr(auth, "_load_auth_identity", load)
        app.dependency_overrides[auth.get_session] = sessions
        app.dependency_overrides[auth.get_current_principal] = principal
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            responses = await asyncio.gather(
                client.get("/api/v1/organizations?limit=100"),
                client.get("/api/v1/organizations/current"),
                client.get("/api/v1/profiles/me"),
            )
            assert [response.status_code for response in responses] == [200, 403, 200]
            assert responses[0].json()["organizations"] == []
        async with maker() as session:
            assert await session.scalar(select(func.count()).select_from(User)) == 1
            assert (
                await session.scalar(select(func.count()).select_from(AuthIdentity))
                == 1
            )

    asyncio.run(run())
