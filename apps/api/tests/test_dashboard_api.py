import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    Artist,
    Campaign,
    Contract,
    MembershipRole,
    Organization,
    Release,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.auth import (
    AuthenticatedPrincipal,
    CurrentUserContext,
    MembershipContext,
    get_current_user_context,
    get_session,
)
from labelos_api.main import create_app


@dataclass(frozen=True)
class DashboardSeed:
    user_id: UUID
    org_a_id: UUID
    org_b_id: UUID


@pytest.fixture
def dashboard_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, DashboardSeed]]:
    monkeypatch.setenv("APP_ENV", "test")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> DashboardSeed:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            owner = User(email="owner@example.com", display_name="Owner")
            org_a = Organization(
                name="Alpha Label",
                slug="alpha-label",
                workos_organization_id="org_ALPHA",
                owner=owner,
            )
            org_b = Organization(
                name="Beta Label",
                slug="beta-label",
                workos_organization_id="org_BETA",
                owner=owner,
            )
            artist_a = Artist(name="Artist A", organization=org_a)
            artist_b = Artist(name="Artist B", organization=org_a)
            outside_artist = Artist(name="Outside Artist", organization=org_b)
            release_a = Release(
                title="Release A",
                artist=artist_a,
                organization=org_a,
            )
            release_b = Release(
                title="Release B",
                artist=artist_b,
                organization=org_a,
            )
            outside_release = Release(
                title="Outside Release",
                artist=outside_artist,
                organization=org_b,
            )
            session.add_all(
                [
                    owner,
                    org_a,
                    org_b,
                    artist_a,
                    artist_b,
                    outside_artist,
                    release_a,
                    release_b,
                    outside_release,
                    Campaign(name="Campaign A", release=release_a, organization=org_a),
                    Campaign(name="Campaign B", release=release_b, organization=org_a),
                    Campaign(
                        name="Outside Campaign",
                        release=outside_release,
                        organization=org_b,
                    ),
                    Contract(title="Contract A", artist=artist_a, organization=org_a),
                    Contract(title="Contract B", artist=artist_b, organization=org_a),
                    Contract(
                        title="Outside Contract",
                        artist=outside_artist,
                        organization=org_b,
                    ),
                ]
            )
            await session.commit()
            return DashboardSeed(
                user_id=owner.id,
                org_a_id=org_a.id,
                org_b_id=org_b.id,
            )

    seeded = asyncio.run(prepare_database())
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    with TestClient(app) as client:
        yield client, seeded

    asyncio.run(engine.dispose())


def _set_active_organization(
    client: TestClient,
    seeded: DashboardSeed,
    *,
    organization_id: UUID,
    workos_organization_id: str,
    role: MembershipRole = MembershipRole.admin,
    permissions: tuple[str, ...] = (
        "analytics:view",
        "artists:view",
        "releases:view",
        "campaigns:view",
        "contracts:view",
        "members:manage",
    ),
    department_access: tuple[str, ...] = (
        "administration",
        "analytics",
        "contracts",
        "finance",
        "legal",
    ),
) -> None:
    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(id=seeded.user_id, email="owner@example.com"),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject="user_01TEST",
                session_id="session_SECRET",
                organization_id=workos_organization_id,
                role=role.value,
                roles=(role.value,),
                permissions=permissions,
            ),
            memberships=(
                MembershipContext(
                    organization_id=organization_id,
                    organization_name="Active Label",
                    organization_slug="active-label",
                    workos_organization_id=workos_organization_id,
                    role=role,
                    department_access=department_access,
                ),
            ),
        )

    client.app.dependency_overrides[get_current_user_context] = override_context


def test_dashboard_summary_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_dashboard_summary_is_scoped_to_active_organization(
    dashboard_client: tuple[TestClient, DashboardSeed],
) -> None:
    client, seeded = dashboard_client
    _set_active_organization(
        client,
        seeded,
        organization_id=seeded.org_a_id,
        workos_organization_id="org_ALPHA",
    )

    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    assert response.json() == {
        "active_artists": 2,
        "upcoming_releases": 2,
        "active_campaigns": 2,
        "pending_approvals": 2,
        "releasePipeline": {
            "planning": 2,
            "production": 0,
            "distribution": 0,
            "scheduled": 0,
            "released": 0,
        },
        "availableCards": [
            "active-artists",
            "upcoming-releases",
            "active-campaigns",
            "tasks-approvals",
        ],
        "availableSections": [
            "release-pipeline",
            "label-performance",
            "member-activity",
        ],
        "authorization": {
            "role": "admin",
            "permissions": [
                "members:manage",
                "artists:view",
                "releases:view",
                "campaigns:view",
                "analytics:view",
                "contracts:view",
            ],
        },
    }
    assert "org_ALPHA" not in response.text
    assert "session_SECRET" not in response.text


def test_dashboard_summary_blocks_organization_b_data_for_organization_a_user(
    dashboard_client: tuple[TestClient, DashboardSeed],
) -> None:
    client, seeded = dashboard_client
    _set_active_organization(
        client,
        seeded,
        organization_id=seeded.org_a_id,
        workos_organization_id="org_ALPHA",
    )

    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_artists"] == 2
    assert payload["upcoming_releases"] == 2
    assert payload["active_campaigns"] == 2
    assert payload["pending_approvals"] == 2
    assert payload["releasePipeline"]["planning"] == 2
    assert payload["active_artists"] != 3
    assert payload["upcoming_releases"] != 3
    assert payload["active_campaigns"] != 3
    assert payload["pending_approvals"] != 3
    assert "Outside Artist" not in response.text
    assert "Outside Release" not in response.text
    assert "Outside Campaign" not in response.text
    assert "Outside Contract" not in response.text


def test_dashboard_summary_does_not_return_another_organizations_counts(
    dashboard_client: tuple[TestClient, DashboardSeed],
) -> None:
    client, seeded = dashboard_client
    _set_active_organization(
        client,
        seeded,
        organization_id=seeded.org_b_id,
        workos_organization_id="org_BETA",
    )

    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    assert response.json() == {
        "active_artists": 1,
        "upcoming_releases": 1,
        "active_campaigns": 1,
        "pending_approvals": 1,
        "releasePipeline": {
            "planning": 1,
            "production": 0,
            "distribution": 0,
            "scheduled": 0,
            "released": 0,
        },
        "availableCards": [
            "active-artists",
            "upcoming-releases",
            "active-campaigns",
            "tasks-approvals",
        ],
        "availableSections": [
            "release-pipeline",
            "label-performance",
            "member-activity",
        ],
        "authorization": {
            "role": "admin",
            "permissions": [
                "members:manage",
                "artists:view",
                "releases:view",
                "campaigns:view",
                "analytics:view",
                "contracts:view",
            ],
        },
    }


def test_dashboard_summary_omits_unauthorized_sensitive_cards(
    dashboard_client: tuple[TestClient, DashboardSeed],
) -> None:
    client, seeded = dashboard_client
    _set_active_organization(
        client,
        seeded,
        organization_id=seeded.org_a_id,
        workos_organization_id="org_ALPHA",
        role=MembershipRole.member,
        permissions=("artists:view", "releases:view"),
        department_access=(),
    )

    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    assert response.json() == {
        "active_artists": 2,
        "upcoming_releases": 2,
        "releasePipeline": {
            "planning": 2,
            "production": 0,
            "distribution": 0,
            "scheduled": 0,
            "released": 0,
        },
        "availableCards": ["active-artists", "upcoming-releases"],
        "availableSections": ["release-pipeline"],
        "authorization": {
            "role": "member",
            "permissions": ["artists:view", "releases:view"],
        },
    }
    assert "pending_approvals" not in response.text


def test_dashboard_performance_returns_normalized_mock_contract(
    dashboard_client: tuple[TestClient, DashboardSeed],
) -> None:
    client, seeded = dashboard_client
    _set_active_organization(
        client,
        seeded,
        organization_id=seeded.org_a_id,
        workos_organization_id="org_ALPHA",
    )

    response = client.get("/api/v1/dashboard/performance?metric=streams&period=30d")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metric"] == "streams"
    assert payload["period"] == "30d"
    assert payload["total"] >= 0
    assert isinstance(payload["changePercent"], float)
    assert payload["source"] == "development_mock"
    assert payload["isMock"] is True
    assert payload["series"]
    assert payload["series"] == sorted(
        payload["series"], key=lambda point: point["date"]
    )
    assert {"date", "value"} <= payload["series"][0].keys()
    assert "org_ALPHA" not in response.text
    assert "session_SECRET" not in response.text


@pytest.mark.parametrize(
    "query",
    [
        "metric=invalid&period=30d",
        "metric=streams&period=invalid",
    ],
)
def test_dashboard_performance_validates_query_contract(
    dashboard_client: tuple[TestClient, DashboardSeed],
    query: str,
) -> None:
    client, seeded = dashboard_client
    _set_active_organization(
        client,
        seeded,
        organization_id=seeded.org_a_id,
        workos_organization_id="org_ALPHA",
    )

    response = client.get(f"/api/v1/dashboard/performance?{query}")

    assert response.status_code == 422


def test_dashboard_performance_requires_analytics_permission(
    dashboard_client: tuple[TestClient, DashboardSeed],
) -> None:
    client, seeded = dashboard_client
    _set_active_organization(
        client,
        seeded,
        organization_id=seeded.org_a_id,
        workos_organization_id="org_ALPHA",
        permissions=("artists:view",),
    )

    response = client.get("/api/v1/dashboard/performance?metric=streams&period=30d")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permission"}


def test_dashboard_performance_requires_report_capability(
    dashboard_client: tuple[TestClient, DashboardSeed],
) -> None:
    client, seeded = dashboard_client
    _set_active_organization(
        client,
        seeded,
        organization_id=seeded.org_a_id,
        workos_organization_id="org_ALPHA",
        role=MembershipRole.member,
        permissions=("analytics:view",),
        department_access=("analytics",),
    )

    response = client.get("/api/v1/dashboard/performance?metric=streams&period=30d")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_dashboard_revenue_performance_requires_royalties_permission(
    dashboard_client: tuple[TestClient, DashboardSeed],
) -> None:
    client, seeded = dashboard_client
    _set_active_organization(
        client,
        seeded,
        organization_id=seeded.org_a_id,
        workos_organization_id="org_ALPHA",
        role=MembershipRole.admin,
        permissions=("analytics:view",),
    )

    response = client.get("/api/v1/dashboard/performance?metric=revenue&period=30d")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permission"}
