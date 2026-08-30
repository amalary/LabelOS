import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    Artist,
    ArtistProfile,
    Campaign,
    CampaignGoal,
    CampaignMilestone,
    MembershipRole,
    Organization,
    OrganizationMembership,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspacePermission,
)
from sqlalchemy import select
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
class SeededAnalyticsApi:
    owner_user_id: UUID
    analyst_user_id: UUID
    workspace_id: UUID
    outside_workspace_id: UUID
    artist_profile_id: UUID
    outside_artist_profile_id: UUID
    campaign_id: UUID
    outside_campaign_id: UUID
    campaign_goal_id: UUID
    campaign_milestone_id: UUID
    outside_campaign_goal_id: UUID


@pytest.fixture
def analytics_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession], SeededAnalyticsApi]]:
    monkeypatch.setenv("APP_ENV", "test")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> SeededAnalyticsApi:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            owner = User(email="analytics-owner@example.com", display_name="Owner")
            analyst = User(
                email="analytics-analyst@example.com",
                display_name="Analyst",
            )
            outside_owner = User(email="analytics-outside@example.com")
            workspace = Organization(
                name="Alpha Label",
                slug="alpha-analytics-api",
                owner=owner,
                workos_organization_id="org_ALPHA_ANALYTICS",
            )
            outside_workspace = Organization(
                name="Beta Label",
                slug="beta-analytics-api",
                owner=outside_owner,
                workos_organization_id="org_BETA_ANALYTICS",
            )
            owner_membership = OrganizationMembership(
                organization=workspace,
                user=owner,
                role=MembershipRole.owner,
                workspace_permission=WorkspacePermission.owner,
                department_access=["analytics", "management"],
            )
            analyst_membership = OrganizationMembership(
                organization=workspace,
                user=analyst,
                role=MembershipRole.guest,
                workspace_permission=WorkspacePermission.guest,
                department_access=["analytics"],
            )
            outside_membership = OrganizationMembership(
                organization=outside_workspace,
                user=outside_owner,
                role=MembershipRole.owner,
                workspace_permission=WorkspacePermission.owner,
                department_access=["analytics", "management"],
            )
            owner_profile = UniversalProfile(
                user=owner,
                slug="analytics-owner",
                display_name="Analytics Owner",
            )
            analyst_profile = UniversalProfile(
                user=analyst,
                slug="analytics-analyst",
                display_name="Analytics Analyst",
            )
            outside_profile = UniversalProfile(
                user=outside_owner,
                slug="analytics-outside",
                display_name="Analytics Outside",
            )
            WorkspaceMembership(
                workspace=workspace,
                profile=owner_profile,
                organization_membership=owner_membership,
                status="active",
            )
            WorkspaceMembership(
                workspace=workspace,
                profile=analyst_profile,
                organization_membership=analyst_membership,
                status="active",
            )
            WorkspaceMembership(
                workspace=outside_workspace,
                profile=outside_profile,
                organization_membership=outside_membership,
                status="active",
            )
            artist = Artist(name="Alpha Artist", organization=workspace)
            outside_artist = Artist(name="Beta Artist", organization=outside_workspace)
            artist_profile = ArtistProfile(
                artist=artist,
                universal_profile=analyst_profile,
                stage_name="Alpha Artist",
            )
            outside_artist_profile = ArtistProfile(
                artist=outside_artist,
                universal_profile=outside_profile,
                stage_name="Beta Artist",
            )
            campaign = Campaign(name="Alpha Campaign", organization=workspace)
            outside_campaign = Campaign(
                name="Beta Campaign",
                organization=outside_workspace,
            )
            campaign_goal = CampaignGoal(campaign=campaign, title="Pre-save Goal")
            campaign_milestone = CampaignMilestone(
                campaign=campaign,
                title="Creative Approved",
            )
            outside_campaign_goal = CampaignGoal(
                campaign=outside_campaign,
                title="Outside Goal",
            )
            session.add_all(
                [
                    artist_profile,
                    outside_artist_profile,
                    campaign_goal,
                    campaign_milestone,
                    outside_campaign_goal,
                ]
            )
            await session.commit()
            return SeededAnalyticsApi(
                owner_user_id=owner.id,
                analyst_user_id=analyst.id,
                workspace_id=workspace.id,
                outside_workspace_id=outside_workspace.id,
                artist_profile_id=artist_profile.id,
                outside_artist_profile_id=outside_artist_profile.id,
                campaign_id=campaign.id,
                outside_campaign_id=outside_campaign.id,
                campaign_goal_id=campaign_goal.id,
                campaign_milestone_id=campaign_milestone.id,
                outside_campaign_goal_id=outside_campaign_goal.id,
            )

    seeded = asyncio.run(prepare_database())
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    with TestClient(app) as client:
        yield client, sessionmaker, seeded

    asyncio.run(engine.dispose())


def _set_context(
    client: TestClient,
    seeded: SeededAnalyticsApi,
    *,
    user_id: UUID | None = None,
    email: str = "analytics-owner@example.com",
    display_name: str = "Owner",
    workspace_permission: WorkspacePermission = WorkspacePermission.owner,
    capability_permissions: tuple[str, ...] = (),
    department_access: tuple[str, ...] = ("analytics", "management"),
    memberships: tuple[MembershipContext, ...] | None = None,
) -> None:
    resolved_user_id = user_id or seeded.owner_user_id

    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(
                id=resolved_user_id,
                email=email,
                display_name=display_name,
            ),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject=f"user_{resolved_user_id}",
                session_id="session_SECRET",
                email=email,
                display_name=display_name,
                organization_id="org_ALPHA_ANALYTICS",
                role=workspace_permission.value,
                roles=(workspace_permission.value,),
            ),
            memberships=memberships
            or (
                MembershipContext(
                    organization_id=seeded.workspace_id,
                    organization_name="Alpha Label",
                    organization_slug="alpha-analytics-api",
                    workos_organization_id="org_ALPHA_ANALYTICS",
                    workspace_permission=workspace_permission,
                    department_access=department_access,
                    capability_permissions=capability_permissions,
                ),
            ),
        )

    client.app.dependency_overrides[get_current_user_context] = override_context


async def _set_analyst_capabilities(
    sessionmaker: async_sessionmaker[AsyncSession],
    seeded: SeededAnalyticsApi,
    capabilities: tuple[str, ...],
) -> None:
    async with sessionmaker() as session:
        membership = await session.scalar(
            select(OrganizationMembership)
            .where(OrganizationMembership.organization_id == seeded.workspace_id)
            .where(OrganizationMembership.user_id == seeded.analyst_user_id)
        )
        assert membership is not None
        membership.capability_permissions = list(capabilities)
        await session.commit()


def _metric_payload(key: str = "streams", value_type: str = "integer") -> dict:
    return {
        "key": key,
        "display_name": key.title(),
        "value_type": value_type,
        "default_unit": "count",
        "aggregation": "sum",
        "provider": {
            "key": "internal",
            "display_name": "Internal Analytics",
        },
        "metadata": {"category": "engagement"},
    }


def _create_metric(
    client: TestClient,
    workspace_id: UUID,
    key: str = "streams",
    value_type: str = "integer",
) -> dict:
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/analytics/metric-definitions",
        json=_metric_payload(key, value_type),
    )
    assert response.status_code == 201
    return response.json()


def _observation_payload(
    metric_definition_id: str,
    *,
    target_type: str = "campaign",
    campaign_id: UUID | None = None,
    artist_profile_id: UUID | None = None,
    campaign_object_type: str | None = None,
    campaign_object_id: UUID | None = None,
    value_numeric: object = 100,
    observed_at: str = "2026-08-29T12:00:00Z",
    idempotency_key: str | None = None,
) -> dict:
    payload = {
        "metric_definition_id": metric_definition_id,
        "target_type": target_type,
        "observed_at": observed_at,
        "value_numeric": value_numeric,
        "dimensions": {"market": "US"},
        "metadata": {"source": "route-test"},
    }
    if campaign_id is not None:
        payload["campaign_id"] = str(campaign_id)
    if artist_profile_id is not None:
        payload["artist_profile_id"] = str(artist_profile_id)
    if campaign_object_type is not None:
        payload["campaign_object_type"] = campaign_object_type
    if campaign_object_id is not None:
        payload["campaign_object_id"] = str(campaign_object_id)
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    return payload


def test_analytics_routes_require_authentication(client: TestClient) -> None:
    workspace_id = uuid4()

    list_response = client.get(
        f"/api/v1/workspaces/{workspace_id}/analytics/metric-definitions"
    )
    create_response = client.post(
        f"/api/v1/workspaces/{workspace_id}/analytics/observations",
        json={},
    )

    assert list_response.status_code == 401
    assert list_response.json() == {"detail": "Authentication required"}
    assert create_response.status_code == 401
    assert create_response.json() == {"detail": "Authentication required"}


def test_analytics_routes_support_authenticated_metric_and_observation_workflow(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/analytics"

    metric = _create_metric(client, seeded.workspace_id)
    listed_metrics = client.get(f"{base}/metric-definitions")
    observation = client.post(
        f"{base}/observations",
        json=_observation_payload(
            metric["id"],
            campaign_id=seeded.campaign_id,
            idempotency_key="campaign-streams",
        ),
    )
    listed_observations = client.get(f"{base}/observations")

    assert listed_metrics.status_code == 200
    assert listed_metrics.json()["metric_definitions"][0]["key"] == "streams"
    assert observation.status_code == 201
    body = observation.json()
    assert body["workspace_id"] == str(seeded.workspace_id)
    assert body["metric_key"] == "streams"
    assert body["provider_key"] == "internal"
    assert body["target_type"] == "campaign"
    assert body["target_id"] == str(seeded.campaign_id)
    assert body["campaign_id"] == str(seeded.campaign_id)
    assert body["campaign_name"] is None
    assert body["value_numeric"] == "100.000000"
    assert body["unit"] == "count"
    assert body["dimensions"] == {"market": "US"}
    assert body["metadata"] == {"source": "route-test"}
    assert listed_observations.status_code == 200
    assert listed_observations.json()["total"] == 1


def test_analytics_routes_require_view_and_create_capabilities(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, sessionmaker, seeded = analytics_client
    asyncio.run(
        _set_analyst_capabilities(
            sessionmaker,
            seeded,
            ("analytics.create",),
        )
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.analyst_user_id,
        email="analytics-analyst@example.com",
        display_name="Analyst",
        workspace_permission=WorkspacePermission.guest,
        capability_permissions=("analytics.create",),
        department_access=("analytics",),
    )
    base = f"/api/v1/workspaces/{seeded.workspace_id}/analytics"

    missing_view = client.get(f"{base}/metric-definitions")
    created = client.post(f"{base}/metric-definitions", json=_metric_payload())
    assert missing_view.status_code == 403
    assert missing_view.json() == {"detail": "Insufficient capability permission"}
    assert created.status_code == 201

    asyncio.run(
        _set_analyst_capabilities(
            sessionmaker,
            seeded,
            ("analytics.view",),
        )
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.analyst_user_id,
        email="analytics-analyst@example.com",
        display_name="Analyst",
        workspace_permission=WorkspacePermission.guest,
        capability_permissions=("analytics.view",),
        department_access=("analytics",),
    )
    missing_create = client.post(f"{base}/metric-definitions", json=_metric_payload())

    assert missing_create.status_code == 403
    assert missing_create.json() == {"detail": "Insufficient capability permission"}


def test_analytics_routes_hide_cross_workspace_and_invalid_workspace_access(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)

    cross_workspace = client.get(
        f"/api/v1/workspaces/{seeded.outside_workspace_id}"
        "/analytics/metric-definitions"
    )
    invalid_workspace = client.get(
        f"/api/v1/workspaces/{uuid4()}/analytics/metric-definitions"
    )

    assert cross_workspace.status_code == 404
    assert cross_workspace.json() == {"detail": "Not found"}
    assert invalid_workspace.status_code == 404
    assert invalid_workspace.json() == {"detail": "Not found"}


@pytest.mark.parametrize(
    ("payload_updates", "expected_status", "expected_detail"),
    [
        (
            {
                "target_type": "artist_profile",
                "artist_profile_id": "outside_artist_profile_id",
            },
            404,
            "Not found",
        ),
        (
            {"target_type": "campaign", "campaign_id": "outside_campaign_id"},
            404,
            "Not found",
        ),
        (
            {
                "target_type": "campaign_object",
                "campaign_id": "campaign_id",
                "campaign_object_type": "goal",
                "campaign_object_id": "outside_campaign_goal_id",
            },
            404,
            "Not found",
        ),
        (
            {
                "target_type": "campaign_object",
                "campaign_id": "campaign_id",
                "campaign_object_type": "task",
                "campaign_object_id": "campaign_goal_id",
            },
            400,
            "Unsupported campaign object type",
        ),
    ],
)
def test_analytics_observation_route_validates_target_scope_and_type(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
    payload_updates: dict[str, str],
    expected_status: int,
    expected_detail: str,
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    metric = _create_metric(client, seeded.workspace_id)
    payload = _observation_payload(metric["id"], campaign_id=seeded.campaign_id)
    for key, value in payload_updates.items():
        payload[key] = str(getattr(seeded, value)) if value.endswith("_id") else value

    response = client.post(
        f"/api/v1/workspaces/{seeded.workspace_id}/analytics/observations",
        json=payload,
    )

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}


def test_analytics_observation_route_accepts_supported_campaign_child_targets(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    metric = _create_metric(client, seeded.workspace_id)

    goal = client.post(
        f"/api/v1/workspaces/{seeded.workspace_id}/analytics/observations",
        json=_observation_payload(
            metric["id"],
            target_type="campaign_object",
            campaign_id=seeded.campaign_id,
            campaign_object_type="goal",
            campaign_object_id=seeded.campaign_goal_id,
        ),
    )
    milestone = client.post(
        f"/api/v1/workspaces/{seeded.workspace_id}/analytics/observations",
        json=_observation_payload(
            metric["id"],
            target_type="campaign_object",
            campaign_id=seeded.campaign_id,
            campaign_object_type="milestone",
            campaign_object_id=seeded.campaign_milestone_id,
        ),
    )

    assert goal.status_code == 201
    assert goal.json()["target_id"] == str(seeded.campaign_goal_id)
    assert milestone.status_code == 201
    assert milestone.json()["target_id"] == str(seeded.campaign_milestone_id)


def test_analytics_observation_route_validates_metric_definition(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)

    response = client.post(
        f"/api/v1/workspaces/{seeded.workspace_id}/analytics/observations",
        json=_observation_payload(str(uuid4()), campaign_id=seeded.campaign_id),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_analytics_observation_route_deduplicates_by_idempotency_key(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    metric = _create_metric(client, seeded.workspace_id)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/analytics/observations"
    payload = _observation_payload(
        metric["id"],
        campaign_id=seeded.campaign_id,
        idempotency_key="dup-key",
    )

    first = client.post(base, json=payload)
    duplicate_payload = {**payload, "value_numeric": 200}
    duplicate = client.post(base, json=duplicate_payload)
    listed = client.get(base)

    assert first.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == first.json()["id"]
    assert duplicate.json()["value_numeric"] == "100.000000"
    assert listed.json()["total"] == 1


def test_analytics_observations_bulk_route_ingests_authenticated_batch(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    metric = _create_metric(client, seeded.workspace_id)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/analytics/observations"

    response = client.post(
        f"{base}/bulk",
        json={
            "observations": [
                _observation_payload(
                    metric["id"],
                    campaign_id=seeded.campaign_id,
                    value_numeric=100,
                    idempotency_key="route-bulk-1",
                ),
                _observation_payload(
                    metric["id"],
                    target_type="campaign_object",
                    campaign_id=seeded.campaign_id,
                    campaign_object_type="goal",
                    campaign_object_id=seeded.campaign_goal_id,
                    value_numeric=200,
                    idempotency_key="route-bulk-2",
                ),
            ],
        },
    )
    listed = client.get(base)

    assert response.status_code == 201
    body = response.json()
    assert body["created_count"] == 2
    assert body["existing_count"] == 0
    assert body["transaction"] == "all_or_nothing"
    assert [item["index"] for item in body["observations"]] == [0, 1]
    assert body["observations"][1]["observation"]["target_type"] == "campaign_object"
    assert body["observations"][1]["observation"]["campaign_object_id"] == str(
        seeded.campaign_goal_id
    )
    assert listed.json()["total"] == 2


def test_analytics_observations_bulk_route_reuses_existing_idempotency_rows(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    metric = _create_metric(client, seeded.workspace_id)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/analytics/observations"
    payload = _observation_payload(
        metric["id"],
        campaign_id=seeded.campaign_id,
        value_numeric=100,
        idempotency_key="route-bulk-existing",
    )

    first = client.post(base, json=payload)
    reused = client.post(
        f"{base}/bulk",
        json={"observations": [{**payload, "value_numeric": 999}]},
    )
    listed = client.get(base)

    assert first.status_code == 201
    assert reused.status_code == 200
    body = reused.json()
    assert body["created_count"] == 0
    assert body["existing_count"] == 1
    assert body["observations"][0]["created"] is False
    assert body["observations"][0]["observation"]["id"] == first.json()["id"]
    assert body["observations"][0]["observation"]["value_numeric"] == "100.000000"
    assert listed.json()["total"] == 1


def test_analytics_observations_bulk_route_returns_structured_errors_without_writes(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    metric = _create_metric(client, seeded.workspace_id)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/analytics/observations"

    response = client.post(
        f"{base}/bulk",
        json={
            "observations": [
                _observation_payload(
                    metric["id"],
                    campaign_id=seeded.campaign_id,
                    value_numeric=100,
                    idempotency_key="route-bulk-valid-but-rolled-back",
                ),
                _observation_payload(
                    metric["id"],
                    campaign_id=seeded.outside_campaign_id,
                    value_numeric=200,
                    idempotency_key="route-bulk-outside-target",
                ),
                {
                    **_observation_payload(
                        metric["id"],
                        campaign_id=seeded.campaign_id,
                        idempotency_key="route-bulk-bad-value",
                    ),
                    "value_numeric": "not-numeric",
                },
            ],
        },
    )
    listed = client.get(base)

    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "detail": "Analytics bulk ingestion batch is invalid",
            "transaction": "all_or_nothing",
            "errors": [
                {
                    "index": 1,
                    "code": "not_found",
                    "detail": "Campaign not found",
                },
                {
                    "index": 2,
                    "code": "invalid_observation",
                    "detail": "value_numeric must be numeric",
                },
            ],
        }
    }
    assert listed.json()["total"] == 0


def test_analytics_observations_bulk_route_rejects_duplicate_keys_in_request(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    metric = _create_metric(client, seeded.workspace_id)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/analytics/observations"

    response = client.post(
        f"{base}/bulk",
        json={
            "observations": [
                _observation_payload(
                    metric["id"],
                    campaign_id=seeded.campaign_id,
                    idempotency_key="route-duplicate-key",
                ),
                _observation_payload(
                    metric["id"],
                    campaign_id=seeded.campaign_id,
                    idempotency_key="route-duplicate-key",
                ),
            ],
        },
    )
    listed = client.get(base)

    assert response.status_code == 400
    assert response.json()["detail"]["transaction"] == "all_or_nothing"
    assert response.json()["detail"]["errors"] == [
        {
            "index": 1,
            "code": "invalid_observation",
            "detail": "Duplicate idempotency_key in request",
        }
    ]
    assert listed.json()["total"] == 0


@pytest.mark.parametrize(
    ("metric_type", "payload_updates", "expected_status", "expected_detail"),
    [
        (
            "integer",
            {"value_numeric": "not-numeric"},
            400,
            "value_numeric must be numeric",
        ),
        ("integer", {"value_numeric": None}, 400, "value_numeric is required"),
        ("string", {"value_numeric": None}, 400, "value_text is required"),
        ("boolean", {"value_numeric": None}, 400, "value_boolean is required"),
        ("json", {"value_numeric": None}, 400, "value_json is required"),
        ("integer", {"observed_at": "not-a-timestamp"}, 422, None),
        ("integer", {"dimensions": []}, 422, None),
        ("integer", {"metadata": []}, 422, None),
    ],
)
def test_analytics_observation_route_validates_payload_shape_and_typed_values(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
    metric_type: str,
    payload_updates: dict[str, object],
    expected_status: int,
    expected_detail: str | None,
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    metric = _create_metric(
        client,
        seeded.workspace_id,
        f"metric-{uuid4()}",
        metric_type,
    )
    payload = _observation_payload(metric["id"], campaign_id=seeded.campaign_id)
    payload.update(payload_updates)

    response = client.post(
        f"/api/v1/workspaces/{seeded.workspace_id}/analytics/observations",
        json=payload,
    )

    assert response.status_code == expected_status
    if expected_detail is not None:
        assert response.json() == {"detail": expected_detail}


def test_analytics_metric_definition_route_validates_provider_metadata(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    payload = _metric_payload()
    payload["provider"]["metadata"] = []

    response = client.post(
        f"/api/v1/workspaces/{seeded.workspace_id}/analytics/metric-definitions",
        json=payload,
    )

    assert response.status_code == 422


def test_analytics_observation_route_supports_pagination_and_filters(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/analytics/observations"
    streams_metric = _create_metric(client, seeded.workspace_id, "streams")
    saves_metric = _create_metric(client, seeded.workspace_id, "saves")

    first = client.post(
        base,
        json=_observation_payload(
            streams_metric["id"],
            campaign_id=seeded.campaign_id,
            value_numeric=100,
            observed_at="2026-08-28T12:00:00Z",
        ),
    )
    second = client.post(
        base,
        json=_observation_payload(
            streams_metric["id"],
            campaign_id=seeded.campaign_id,
            value_numeric=200,
            observed_at="2026-08-29T12:00:00Z",
        ),
    )
    third = client.post(
        base,
        json=_observation_payload(
            saves_metric["id"],
            target_type="artist_profile",
            artist_profile_id=seeded.artist_profile_id,
            value_numeric=5,
            observed_at="2026-08-30T12:00:00Z",
        ),
    )
    filtered = client.get(
        base,
        params={
            "metric_definition_id": streams_metric["id"],
            "campaign_id": str(seeded.campaign_id),
            "observed_start": "2026-08-29T00:00:00Z",
            "observed_end": "2026-08-29T23:59:59Z",
            "limit": 1,
            "offset": 0,
        },
    )
    paged = client.get(base, params={"limit": 2, "offset": 1})
    invalid_page = client.get(base, params={"limit": 501})

    assert first.status_code == 201
    assert second.status_code == 201
    assert third.status_code == 201
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] == 1
    assert filtered_body["limit"] == 1
    assert filtered_body["observations"][0]["id"] == second.json()["id"]
    assert paged.status_code == 200
    assert paged.json()["total"] == 3
    assert paged.json()["limit"] == 2
    assert paged.json()["offset"] == 1
    assert len(paged.json()["observations"]) == 2
    assert invalid_page.status_code == 422


def test_analytics_routes_filter_artist_profile_relationship_without_target_duplication(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/analytics"
    metric = _create_metric(client, seeded.workspace_id, "artist-streams")

    artist_direct = client.post(
        f"{base}/observations",
        json=_observation_payload(
            metric["id"],
            target_type="artist_profile",
            artist_profile_id=seeded.artist_profile_id,
            value_numeric=100,
            observed_at="2026-08-29T12:00:00Z",
        ),
    )
    artist_campaign_attributed = client.post(
        f"{base}/observations",
        json=_observation_payload(
            metric["id"],
            target_type="campaign",
            campaign_id=seeded.campaign_id,
            artist_profile_id=seeded.artist_profile_id,
            value_numeric=25,
            observed_at="2026-08-30T12:00:00Z",
        ),
    )
    filtered = client.get(
        f"{base}/observations",
        params={
            "artist_profile_id": str(seeded.artist_profile_id),
            "limit": 10,
        },
    )
    series = client.get(
        f"{base}/series",
        params={
            "aggregation": "sum",
            "artist_profile_id": str(seeded.artist_profile_id),
            "metric_definition_id": metric["id"],
        },
    )

    assert artist_direct.status_code == 201
    assert artist_campaign_attributed.status_code == 201
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] == 2
    assert {
        observation["target_type"] for observation in filtered_body["observations"]
    } == {
        "artist_profile",
        "campaign",
    }
    assert {
        observation["campaign_name"]
        for observation in filtered_body["observations"]
        if observation["campaign_id"]
    } == {"Alpha Campaign"}
    assert series.status_code == 200
    assert series.json()["observation_count"] == 2
    assert series.json()["points"] == [
        {
            "bucket_date": "2026-08-29",
            "observation_count": 1,
            "value": "100.000000",
        },
        {
            "bucket_date": "2026-08-30",
            "observation_count": 1,
            "value": "25.000000",
        },
    ]


def test_analytics_reporting_routes_return_latest_series_and_comparison(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/analytics"
    metric = _create_metric(client, seeded.workspace_id, "streams")

    previous = client.post(
        f"{base}/observations",
        json=_observation_payload(
            metric["id"],
            campaign_id=seeded.campaign_id,
            value_numeric=50,
            observed_at="2026-08-22T12:00:00Z",
        ),
    )
    first_current = client.post(
        f"{base}/observations",
        json=_observation_payload(
            metric["id"],
            campaign_id=seeded.campaign_id,
            value_numeric=100,
            observed_at="2026-08-29T12:00:00Z",
        ),
    )
    second_current = client.post(
        f"{base}/observations",
        json=_observation_payload(
            metric["id"],
            campaign_id=seeded.campaign_id,
            value_numeric=25,
            observed_at="2026-08-30T12:00:00Z",
        ),
    )
    params = {
        "metric_definition_id": metric["id"],
        "campaign_id": str(seeded.campaign_id),
    }

    latest = client.get(f"{base}/observations/latest", params=params)
    series = client.get(
        f"{base}/series",
        params={
            **params,
            "aggregation": "sum",
            "observed_start": "2026-08-29T00:00:00Z",
            "observed_end": "2026-08-31T00:00:00Z",
        },
    )
    comparison = client.get(
        f"{base}/comparison",
        params={
            **params,
            "aggregation": "sum",
            "current_start": "2026-08-29T00:00:00Z",
            "current_end": "2026-09-05T00:00:00Z",
        },
    )

    assert previous.status_code == 201
    assert first_current.status_code == 201
    assert second_current.status_code == 201
    assert latest.status_code == 200
    assert latest.json()["id"] == second_current.json()["id"]
    assert series.status_code == 200
    assert series.json()["points"] == [
        {
            "bucket_date": "2026-08-29",
            "value": "100.000000",
            "observation_count": 1,
        },
        {
            "bucket_date": "2026-08-30",
            "value": "25.000000",
            "observation_count": 1,
        },
    ]
    assert comparison.status_code == 200
    comparison_body = comparison.json()
    assert comparison_body["current_value"] == "125.000000"
    assert comparison_body["previous_value"] == "50.000000"
    assert comparison_body["absolute_change"] == "75.000000"
    assert comparison_body["percentage_change"] == "1.500000"
    assert comparison_body["status"] == "compared"


def test_analytics_reporting_routes_filter_campaign_child_objects(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = analytics_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/analytics"
    metric = _create_metric(client, seeded.workspace_id, "goal-progress")

    goal_observation = client.post(
        f"{base}/observations",
        json=_observation_payload(
            metric["id"],
            target_type="campaign_object",
            campaign_id=seeded.campaign_id,
            campaign_object_type="goal",
            campaign_object_id=seeded.campaign_goal_id,
            value_numeric=10,
            observed_at="2026-08-29T12:00:00Z",
        ),
    )
    milestone_observation = client.post(
        f"{base}/observations",
        json=_observation_payload(
            metric["id"],
            target_type="campaign_object",
            campaign_id=seeded.campaign_id,
            campaign_object_type="milestone",
            campaign_object_id=seeded.campaign_milestone_id,
            value_numeric=20,
            observed_at="2026-08-29T13:00:00Z",
        ),
    )

    filtered = client.get(
        f"{base}/series",
        params={
            "metric_definition_id": metric["id"],
            "target_type": "campaign_object",
            "campaign_id": str(seeded.campaign_id),
            "campaign_object_type": "goal",
            "campaign_object_id": str(seeded.campaign_goal_id),
            "aggregation": "sum",
        },
    )
    invalid_child = client.get(
        f"{base}/series",
        params={
            "metric_definition_id": metric["id"],
            "target_type": "campaign_object",
            "campaign_id": str(seeded.campaign_id),
            "campaign_object_type": "task",
            "campaign_object_id": str(seeded.campaign_goal_id),
            "aggregation": "sum",
        },
    )

    assert goal_observation.status_code == 201
    assert milestone_observation.status_code == 201
    assert filtered.status_code == 200
    assert filtered.json()["observation_count"] == 1
    assert filtered.json()["points"][0]["value"] == "10.000000"
    assert invalid_child.status_code == 400
    assert invalid_child.json() == {"detail": "Unsupported campaign object type"}


def test_analytics_openapi_contract_exposes_stable_response_fields(
    analytics_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededAnalyticsApi,
    ],
) -> None:
    client, _sessionmaker, _seeded = analytics_client

    schema = client.get("/openapi.json").json()
    provider_schema = schema["components"]["schemas"]["AnalyticsProviderResponse"]
    metric_schema = schema["components"]["schemas"]["AnalyticsMetricDefinitionResponse"]
    observation_schema = schema["components"]["schemas"]["AnalyticsObservationResponse"]
    observations_list_schema = schema["components"]["schemas"][
        "AnalyticsObservationsListResponse"
    ]

    assert set(provider_schema["properties"]) == {
        "id",
        "workspace_id",
        "key",
        "display_name",
        "provider_type",
        "external_account_id",
        "metadata",
        "created_at",
        "updated_at",
    }
    assert set(metric_schema["properties"]) == {
        "id",
        "workspace_id",
        "provider",
        "key",
        "display_name",
        "description",
        "value_type",
        "default_unit",
        "aggregation",
        "metadata",
        "created_at",
        "updated_at",
    }
    assert set(observation_schema["properties"]) == {
        "id",
        "workspace_id",
        "metric_definition_id",
        "metric_key",
        "provider_id",
        "provider_key",
        "target_type",
        "target_id",
        "artist_profile_id",
        "campaign_id",
        "campaign_name",
        "campaign_object_type",
        "campaign_object_id",
        "value_numeric",
        "value_text",
        "value_boolean",
        "value_json",
        "unit",
        "observed_at",
        "source_record_id",
        "idempotency_key",
        "dimensions",
        "metadata",
        "created_at",
        "updated_at",
    }
    assert set(observations_list_schema["properties"]) == {
        "observations",
        "total",
        "limit",
        "offset",
    }
