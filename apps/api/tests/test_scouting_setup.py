import asyncio

import pytest
from labelos_database.models import (
    CollectionRun,
    DatasetDocumentation,
    GovernanceActivity,
)
from sqlalchemy import func, select

from labelos_api.config import get_settings
from test_scouting import scout
from test_youtube_research_api import configured as configured
from test_youtube_research_api import research_client as research_client


def test_setup_is_idempotent_audited_and_never_claims_approval(configured):
    client, maker, seeded, _, calls = configured
    url = f"/api/v1/workspaces/{seeded.workspace_id}/scouting/local-session"
    first = client.post(url)
    assert first.status_code == 201, first.text
    second = client.post(url)
    assert second.status_code == 200 and second.json() == first.json()
    assert second.headers["cache-control"] == "no-store"
    assert calls == {"store": 0, "secret": 0, "http": []}

    async def check():
        async with maker() as session:
            assert (
                await session.scalar(select(func.count()).select_from(CollectionRun))
                == 1
            )
            run = await session.scalar(select(CollectionRun))
            assert run.status == "running" and not run.production
            doc = await session.scalar(select(DatasetDocumentation))
            assert doc.state == "draft" and not doc.production_eligible
            assert not doc.document["license_approved"]
            assert not doc.document["privacy_reviewed"]
            assert (
                await session.scalar(
                    select(func.count()).select_from(GovernanceActivity)
                )
                == 6
            )

    asyncio.run(check())


def test_ordinary_scout_cannot_prepare_sessions(configured):
    client, _, _, base = scout(configured)
    assert client.post(base + "/local-session").status_code == 403


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_setup_unavailable_outside_development(configured, environment):
    client, _, seeded, settings, _ = configured
    client.app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={"environment": environment}
    )
    assert (
        client.post(
            f"/api/v1/workspaces/{seeded.workspace_id}/scouting/local-session"
        ).status_code
        == 404
    )


def test_setup_does_not_cross_workspace_boundary(configured):
    client, _, seeded, _, _ = configured
    assert (
        client.post(
            f"/api/v1/workspaces/{seeded.outside_workspace_id}/scouting/local-session"
        ).status_code
        == 403
    )
    client.app.dependency_overrides.clear()
    assert (
        client.post(
            f"/api/v1/workspaces/{seeded.workspace_id}/scouting/local-session"
        ).status_code
        == 401
    )


def test_concurrent_local_setup_postgres(postgres_test_engine):
    from labelos_database.models import User

    from labelos_api.services.scouting_setup import prepare_local_session
    from test_governance import prepare_governance_db

    async def run():
        maker, workspace_id, owner_id = await prepare_governance_db(
            postgres_test_engine
        )

        async def setup():
            async with maker() as session:
                owner = await session.get(User, owner_id)
                row, created = await prepare_local_session(session, workspace_id, owner)
                await session.commit()
                return row.id, created

        results = await asyncio.gather(*(setup() for _ in range(6)))
        assert len({row[0] for row in results}) == 1
        assert sum(row[1] for row in results) == 1

    asyncio.run(run())
