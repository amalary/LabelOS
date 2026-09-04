import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.capabilities import Capability
from labelos_database.models import (
    Artist,
    Campaign,
    MembershipRole,
    Organization,
    OrganizationMembership,
    RealtimeEvent,
    Release,
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
from labelos_api.realtime import RealtimeEventType, realtime_channel


@dataclass(frozen=True)
class SeededMarketingContentApi:
    owner_user_id: UUID
    viewer_user_id: UUID
    approver_user_id: UUID
    workspace_id: UUID
    outside_workspace_id: UUID
    owner_profile_id: UUID
    viewer_profile_id: UUID
    approver_profile_id: UUID
    outside_profile_id: UUID
    artist_id: UUID
    outside_artist_id: UUID
    release_id: UUID
    outside_release_id: UUID
    campaign_id: UUID
    second_campaign_id: UUID
    outside_campaign_id: UUID


@pytest.fixture
def marketing_content_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[
    tuple[TestClient, async_sessionmaker[AsyncSession], SeededMarketingContentApi]
]:
    monkeypatch.setenv("APP_ENV", "test")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> SeededMarketingContentApi:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            owner = User(email="marketing-owner@example.com", display_name="Owner")
            viewer = User(email="marketing-viewer@example.com", display_name="Viewer")
            outside_owner = User(email="marketing-outside@example.com")
            workspace = Organization(
                name="Alpha Label",
                slug="alpha-marketing-content-api",
                owner=owner,
                workos_organization_id="org_ALPHA_MARKETING_CONTENT",
            )
            outside_workspace = Organization(
                name="Beta Label",
                slug="beta-marketing-content-api",
                owner=outside_owner,
                workos_organization_id="org_BETA_MARKETING_CONTENT",
            )
            owner_membership = OrganizationMembership(
                organization=workspace,
                user=owner,
                role=MembershipRole.owner,
                workspace_permission=WorkspacePermission.owner,
                department_access=["marketing", "management"],
            )
            viewer_membership = OrganizationMembership(
                organization=workspace,
                user=viewer,
                role=MembershipRole.guest,
                workspace_permission=WorkspacePermission.guest,
                department_access=["marketing"],
            )
            outside_membership = OrganizationMembership(
                organization=outside_workspace,
                user=outside_owner,
                role=MembershipRole.owner,
                workspace_permission=WorkspacePermission.owner,
                department_access=["marketing", "management"],
            )
            owner_profile = UniversalProfile(
                user=owner,
                slug="marketing-owner",
                display_name="Marketing Owner",
            )
            viewer_profile = UniversalProfile(
                user=viewer,
                slug="marketing-viewer",
                display_name="Marketing Viewer",
            )
            approver_profile = UniversalProfile(
                user=User(email="marketing-approver-profile@example.com"),
                slug="marketing-approver",
                display_name="Marketing Approver",
            )
            approver_membership = OrganizationMembership(
                organization=workspace,
                user=approver_profile.user,
                role=MembershipRole.guest,
                workspace_permission=WorkspacePermission.guest,
                department_access=["marketing"],
                capability_permissions=[
                    Capability.marketing_content_view.value,
                    Capability.marketing_content_approve.value,
                ],
            )
            outside_profile = UniversalProfile(
                user=outside_owner,
                slug="marketing-outside",
                display_name="Marketing Outside",
            )
            WorkspaceMembership(
                workspace=workspace,
                profile=owner_profile,
                organization_membership=owner_membership,
                status="active",
            )
            WorkspaceMembership(
                workspace=workspace,
                profile=viewer_profile,
                organization_membership=viewer_membership,
                status="active",
            )
            WorkspaceMembership(
                workspace=workspace,
                profile=approver_profile,
                organization_membership=approver_membership,
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
            release = Release(
                title="Alpha Single",
                organization=workspace,
                artist=artist,
            )
            outside_release = Release(
                title="Beta Single",
                organization=outside_workspace,
                artist=outside_artist,
            )
            campaign = Campaign(name="Alpha Campaign", organization=workspace)
            second_campaign = Campaign(name="Second Campaign", organization=workspace)
            outside_campaign = Campaign(
                name="Beta Campaign",
                organization=outside_workspace,
            )
            session.add_all(
                [
                    viewer_membership,
                    approver_membership,
                    release,
                    outside_release,
                    campaign,
                    second_campaign,
                    outside_campaign,
                ]
            )
            await session.commit()
            return SeededMarketingContentApi(
                owner_user_id=owner.id,
                viewer_user_id=viewer.id,
                approver_user_id=approver_profile.user_id,
                workspace_id=workspace.id,
                outside_workspace_id=outside_workspace.id,
                owner_profile_id=owner_profile.id,
                viewer_profile_id=viewer_profile.id,
                approver_profile_id=approver_profile.id,
                outside_profile_id=outside_profile.id,
                artist_id=artist.id,
                outside_artist_id=outside_artist.id,
                release_id=release.id,
                outside_release_id=outside_release.id,
                campaign_id=campaign.id,
                second_campaign_id=second_campaign.id,
                outside_campaign_id=outside_campaign.id,
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
    seeded: SeededMarketingContentApi,
    *,
    user_id: UUID | None = None,
    email: str = "marketing-owner@example.com",
    workspace_permission: WorkspacePermission = WorkspacePermission.owner,
    capability_permissions: tuple[str, ...] = (),
    department_access: tuple[str, ...] = ("marketing", "management"),
    memberships: tuple[MembershipContext, ...] | None = None,
) -> None:
    resolved_user_id = user_id or seeded.owner_user_id

    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(id=resolved_user_id, email=email),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject=f"user_{resolved_user_id}",
                session_id="session_SECRET",
                email=email,
                organization_id="org_ALPHA_MARKETING_CONTENT",
                role=workspace_permission.value,
                roles=(workspace_permission.value,),
            ),
            memberships=memberships
            or (
                MembershipContext(
                    organization_id=seeded.workspace_id,
                    organization_name="Alpha Label",
                    organization_slug="alpha-marketing-content-api",
                    workos_organization_id="org_ALPHA_MARKETING_CONTENT",
                    workspace_permission=workspace_permission,
                    department_access=department_access,
                    capability_permissions=capability_permissions,
                ),
            ),
        )

    client.app.dependency_overrides[get_current_user_context] = override_context


async def _set_viewer_capabilities(
    sessionmaker: async_sessionmaker[AsyncSession],
    seeded: SeededMarketingContentApi,
    capabilities: tuple[str, ...],
) -> None:
    async with sessionmaker() as session:
        membership = await session.scalar(
            select(OrganizationMembership)
            .where(OrganizationMembership.organization_id == seeded.workspace_id)
            .where(OrganizationMembership.user_id == seeded.viewer_user_id)
        )
        assert membership is not None
        membership.capability_permissions = list(capabilities)
        await session.commit()


def _base(seeded: SeededMarketingContentApi, campaign_id: UUID | None = None) -> str:
    resolved_campaign_id = campaign_id or seeded.campaign_id
    return (
        f"/api/v1/workspaces/{seeded.workspace_id}/campaigns/"
        f"{resolved_campaign_id}/marketing-content"
    )


def _approvals_base(seeded: SeededMarketingContentApi) -> str:
    return f"/api/v1/workspaces/{seeded.workspace_id}/approvals"


def _approval_submit_base(
    seeded: SeededMarketingContentApi,
    content_id: str,
    campaign_id: UUID | None = None,
) -> str:
    return f"{_base(seeded, campaign_id)}/{content_id}/approval-requests"


async def _realtime_events(
    sessionmaker: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> list[RealtimeEvent]:
    async with sessionmaker() as session:
        rows = await session.scalars(
            select(RealtimeEvent)
            .where(RealtimeEvent.organization_id == organization_id)
            .order_by(RealtimeEvent.created_at.asc(), RealtimeEvent.id.asc())
        )
        return list(rows.all())


def _draft_payload(
    seeded: SeededMarketingContentApi,
    *,
    title: str = "Launch Caption",
    scheduled_at: datetime | None = None,
) -> dict:
    payload = {
        "title": title,
        "content_type": "Social Post",
        "copy_text": "Pre-save now.",
        "asset_refs": [{"kind": "image", "id": "asset-1"}],
        "artist_id": str(seeded.artist_id),
        "release_id": str(seeded.release_id),
        "owner_profile_id": str(seeded.owner_profile_id),
    }
    if scheduled_at is not None:
        payload["scheduled_at"] = scheduled_at.isoformat()
    return payload


def test_marketing_content_routes_require_authentication(client: TestClient) -> None:
    response = client.get(
        f"/api/v1/workspaces/{uuid4()}/campaigns/{uuid4()}/marketing-content"
    )
    assert response.status_code == 401


def test_marketing_content_campaign_crud_and_lifecycle(
    marketing_content_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededMarketingContentApi,
    ],
) -> None:
    client, _sessionmaker, seeded = marketing_content_client
    _set_context(client, seeded)
    base = _base(seeded)
    scheduled_at = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

    created = client.post(base, json=_draft_payload(seeded)).json()
    assert created["status"] == "draft"
    assert created["created_by_profile_id"] == str(seeded.owner_profile_id)

    multi_channel = client.post(
        base,
        json={
            **_draft_payload(seeded, title="Multi Channel"),
            "scheduled_at": scheduled_at.isoformat(),
            "channels": [
                {
                    "channel": "Instagram",
                    "placement": "Reel",
                    "scheduled_at": scheduled_at.isoformat(),
                    "copy_text_override": "IG copy",
                    "asset_refs": [{"kind": "video", "id": "ig-1"}],
                },
                {"channel": "TikTok", "asset_refs": [{"kind": "video", "id": "tt-1"}]},
            ],
        },
    ).json()
    assert [channel["channel"] for channel in multi_channel["channels"]] == [
        "instagram",
        "tiktok",
    ]

    got = client.get(f"{base}/{created['id']}")
    assert got.status_code == 200
    assert got.json()["title"] == "Launch Caption"

    updated = client.patch(
        f"{base}/{created['id']}",
        json={"title": "Launch Caption Final", "copy_text": None},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Launch Caption Final"
    assert updated.json()["copy_text"] is None

    listed = client.get(base)
    assert listed.status_code == 200
    assert listed.json()["total"] == 2

    submitted = client.patch(
        f"{base}/{created['id']}/status",
        json={"status": "in_review"},
    )
    assert submitted.status_code == 200
    assert submitted.json()["approval_requested_at"] is not None

    _set_context(
        client,
        seeded,
        user_id=seeded.approver_user_id,
        email="marketing-approver-profile@example.com",
        capability_permissions=(
            Capability.marketing_content_view.value,
            Capability.marketing_content_approve.value,
        ),
        department_access=("marketing",),
    )
    approved = client.patch(
        f"{base}/{created['id']}/status",
        json={"status": "approved"},
    )
    assert approved.status_code == 200
    assert approved.json()["approved_by_profile_id"] == str(seeded.approver_profile_id)
    _set_context(client, seeded)

    cannot_schedule = client.patch(
        f"{base}/{created['id']}/status",
        json={"status": "scheduled"},
    )
    assert cannot_schedule.status_code == 409

    client.patch(
        f"{base}/{multi_channel['id']}/status",
        json={"status": "in_review"},
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.approver_user_id,
        email="marketing-approver-profile@example.com",
        capability_permissions=(
            Capability.marketing_content_view.value,
            Capability.marketing_content_approve.value,
        ),
        department_access=("marketing",),
    )
    approved_multi = client.patch(
        f"{base}/{multi_channel['id']}/status",
        json={
            "status": "approved",
            "approved_by_profile_id": str(seeded.approver_profile_id),
        },
    )
    assert approved_multi.status_code == 200
    _set_context(client, seeded)
    scheduled = client.patch(
        f"{base}/{multi_channel['id']}/status",
        json={"status": "scheduled"},
    )
    assert scheduled.status_code == 200
    assert scheduled.json()["status"] == "scheduled"

    archived = client.post(f"{base}/{created['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"


def test_marketing_content_mutations_publish_workspace_scoped_realtime_events(
    marketing_content_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededMarketingContentApi,
    ],
) -> None:
    client, sessionmaker, seeded = marketing_content_client
    _set_context(client, seeded)
    base = _base(seeded)
    scheduled_at = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

    created_response = client.post(base, json=_draft_payload(seeded))
    assert created_response.status_code == 201
    content_id = created_response.json()["id"]

    updated_response = client.patch(
        f"{base}/{content_id}",
        json={"title": "Realtime Caption Final"},
    )
    in_review_response = client.patch(
        f"{base}/{content_id}/status",
        json={"status": "in_review"},
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.approver_user_id,
        email="marketing-approver-profile@example.com",
        capability_permissions=(
            Capability.marketing_content_view.value,
            Capability.marketing_content_approve.value,
        ),
        department_access=("marketing",),
    )
    approved_response = client.patch(
        f"{base}/{content_id}/status",
        json={"status": "approved"},
    )

    assert updated_response.status_code == 200
    assert in_review_response.status_code == 200
    assert approved_response.status_code == 200

    events = asyncio.run(_realtime_events(sessionmaker, seeded.workspace_id))
    assert [event.event_type for event in events] == [
        RealtimeEventType.marketing_content_created.value,
        RealtimeEventType.marketing_content_updated.value,
        RealtimeEventType.approval_updated.value,
        RealtimeEventType.approval_updated.value,
    ]
    assert all(event.organization_id == seeded.workspace_id for event in events)
    assert all(
        event.channel == realtime_channel(seeded.workspace_id) for event in events
    )
    assert [event.entity_type for event in events] == [
        "marketing_content_item",
        "marketing_content_item",
        "approval_request",
        "approval_request",
    ]
    assert [event.entity_id for event in events[:2]] == [content_id, content_id]
    assert [event.actor_user_id for event in events] == [
        seeded.owner_user_id,
        seeded.owner_user_id,
        seeded.owner_user_id,
        seeded.approver_user_id,
    ]
    for event in events:
        assert event.payload["contentItemId"] == content_id
        assert event.payload["campaignId"] == str(seeded.campaign_id)
    assert events[0].payload["status"] == "draft"
    assert events[2].payload["status"] == "in_review"
    assert events[3].payload["status"] == "approved"

    _set_context(client, seeded)
    schedulable = client.post(
        base,
        json={
            **_draft_payload(seeded, title="Publishable"),
            "scheduled_at": scheduled_at.isoformat(),
        },
    ).json()
    assert (
        client.patch(
            f"{base}/{schedulable['id']}/status",
            json={"status": "in_review"},
        ).status_code
        == 200
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.approver_user_id,
        email="marketing-approver-profile@example.com",
        capability_permissions=(
            Capability.marketing_content_view.value,
            Capability.marketing_content_approve.value,
        ),
        department_access=("marketing",),
    )
    assert (
        client.patch(
            f"{base}/{schedulable['id']}/status",
            json={"status": "approved"},
        ).status_code
        == 200
    )
    _set_context(client, seeded)
    scheduled = client.patch(
        f"{base}/{schedulable['id']}/status",
        json={"status": "scheduled"},
    )
    published = client.patch(
        f"{base}/{schedulable['id']}/status",
        json={"status": "published"},
    )
    assert scheduled.status_code == 200
    assert published.status_code == 200
    publish_events = asyncio.run(_realtime_events(sessionmaker, seeded.workspace_id))[
        -2:
    ]
    assert [event.event_type for event in publish_events] == [
        RealtimeEventType.marketing_content_status_changed.value,
        RealtimeEventType.marketing_content_published.value,
    ]
    assert publish_events[0].payload["status"] == "scheduled"
    assert publish_events[1].payload["status"] == "published"

    assert (
        asyncio.run(_realtime_events(sessionmaker, seeded.outside_workspace_id)) == []
    )


def test_marketing_content_does_not_publish_realtime_event_on_failed_mutation(
    marketing_content_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededMarketingContentApi,
    ],
) -> None:
    client, sessionmaker, seeded = marketing_content_client
    _set_context(client, seeded)

    response = client.post(
        _base(seeded),
        json={
            **_draft_payload(seeded, title="Invalid Relationship"),
            "artist_id": str(seeded.outside_artist_id),
        },
    )

    assert response.status_code == 400
    assert asyncio.run(_realtime_events(sessionmaker, seeded.workspace_id)) == []


def test_marketing_content_workspace_calendar_filters(
    marketing_content_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededMarketingContentApi,
    ],
) -> None:
    client, _sessionmaker, seeded = marketing_content_client
    _set_context(client, seeded)
    first_date = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    second_date = first_date + timedelta(days=10)

    first = client.post(
        _base(seeded),
        json={
            **_draft_payload(seeded, title="First"),
            "scheduled_at": first_date.isoformat(),
            "channels": [{"channel": "Instagram"}],
        },
    ).json()
    second = client.post(
        _base(seeded, seeded.second_campaign_id),
        json={
            "title": "Second",
            "content_type": "Video",
            "scheduled_at": second_date.isoformat(),
            "channels": [{"channel": "TikTok"}],
        },
    ).json()
    channel_only = client.post(
        _base(seeded),
        json={
            "title": "Channel Only",
            "content_type": "Image",
            "channels": [
                {
                    "channel": "Threads",
                    "scheduled_at": first_date.isoformat(),
                }
            ],
        },
    ).json()
    client.patch(f"{_base(seeded)}/{first['id']}/status", json={"status": "in_review"})

    workspace_base = f"/api/v1/workspaces/{seeded.workspace_id}/marketing-content"
    date_filtered = client.get(
        workspace_base,
        params={
            "start": (first_date - timedelta(days=1)).isoformat(),
            "end": (first_date + timedelta(days=1)).isoformat(),
        },
    )
    campaign_filtered = client.get(
        workspace_base,
        params={"campaign_id": str(seeded.second_campaign_id)},
    )
    artist_filtered = client.get(
        workspace_base,
        params={"artist_id": str(seeded.artist_id)},
    )
    status_filtered = client.get(workspace_base, params={"status": "in_review"})
    channel_filtered = client.get(workspace_base, params={"channel": "TikTok"})
    type_filtered = client.get(workspace_base, params={"content_type": "Video"})

    assert {item["id"] for item in date_filtered.json()["marketing_content"]} == {
        first["id"],
        channel_only["id"],
    }
    assert [item["id"] for item in campaign_filtered.json()["marketing_content"]] == [
        second["id"]
    ]
    assert [item["id"] for item in artist_filtered.json()["marketing_content"]] == [
        first["id"]
    ]
    assert [item["id"] for item in status_filtered.json()["marketing_content"]] == [
        first["id"]
    ]
    assert [item["id"] for item in channel_filtered.json()["marketing_content"]] == [
        second["id"]
    ]
    assert [item["id"] for item in type_filtered.json()["marketing_content"]] == [
        second["id"]
    ]


def test_marketing_content_authorization_and_scope_errors(
    marketing_content_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededMarketingContentApi,
    ],
) -> None:
    client, sessionmaker, seeded = marketing_content_client
    _set_context(client, seeded)
    created = client.post(_base(seeded), json=_draft_payload(seeded)).json()

    asyncio.run(
        _set_viewer_capabilities(
            sessionmaker,
            seeded,
            (Capability.marketing_content_view.value,),
        )
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        email="marketing-viewer@example.com",
        workspace_permission=WorkspacePermission.guest,
        capability_permissions=(Capability.marketing_content_view.value,),
        department_access=("marketing",),
    )

    assert client.get(f"{_base(seeded)}/{created['id']}").status_code == 200
    assert client.post(_base(seeded), json=_draft_payload(seeded)).status_code == 403
    assert (
        client.patch(
            f"{_base(seeded)}/{created['id']}",
            json={"title": "Denied"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"{_base(seeded)}/{created['id']}/status",
            json={"status": "in_review"},
        ).status_code
        == 403
    )
    assert client.post(f"{_base(seeded)}/{created['id']}/archive").status_code == 403

    _set_context(client, seeded)
    invalid_campaign = client.post(
        _base(seeded, seeded.outside_campaign_id),
        json={"title": "Outside", "content_type": "Image"},
    )
    cross_workspace = client.get(
        f"/api/v1/workspaces/{seeded.outside_workspace_id}/campaigns/"
        f"{seeded.outside_campaign_id}/marketing-content/{created['id']}"
    )
    cross_campaign = client.get(
        f"{_base(seeded, seeded.second_campaign_id)}/{created['id']}"
    )

    assert invalid_campaign.status_code == 404
    assert cross_workspace.status_code in {403, 404}
    assert cross_campaign.status_code == 404


def test_marketing_content_rejects_invalid_input_and_lifecycle(
    marketing_content_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededMarketingContentApi,
    ],
) -> None:
    client, _sessionmaker, seeded = marketing_content_client
    _set_context(client, seeded)
    base = _base(seeded)

    invalid_channel = client.post(
        base,
        json={
            "title": "Bad Channel",
            "content_type": "Image",
            "channels": [{"channel": "Instagram"}, {"channel": "instagram"}],
        },
    )
    naive_datetime = client.post(
        base,
        json={
            "title": "Naive",
            "content_type": "Image",
            "scheduled_at": "2026-09-10T12:00:00",
        },
    )
    created = client.post(
        base,
        json={
            "title": "Lifecycle",
            "content_type": "Image",
            "artist_id": str(seeded.outside_artist_id),
        },
    )
    lifecycle = client.post(base, json={"title": "Lifecycle", "content_type": "Image"})
    invalid_transition = client.patch(
        f"{base}/{lifecycle.json()['id']}/status",
        json={"status": "published"},
    )
    lifecycle_unknown = client.patch(
        f"{base}/{lifecycle.json()['id']}/status",
        json={"status": "unknown"},
    )

    assert invalid_channel.status_code == 400
    assert naive_datetime.status_code == 422
    assert created.status_code == 400
    assert invalid_transition.status_code == 409
    assert lifecycle_unknown.status_code == 422


def test_marketing_content_openapi_contract_exposes_stable_routes(
    marketing_content_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededMarketingContentApi,
    ],
) -> None:
    client, _sessionmaker, _seeded = marketing_content_client
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    schemas = schema["components"]["schemas"]

    assert "/api/v1/workspaces/{workspace_id}/marketing-content" in paths
    assert (
        "/api/v1/workspaces/{workspace_id}/campaigns/{campaign_id}/marketing-content"
        in paths
    )
    assert (
        "/api/v1/workspaces/{workspace_id}/campaigns/{campaign_id}/marketing-content/{content_id}/status"
        in paths
    )
    assert set(schemas["MarketingContentCreateRequest"]["properties"]) == {
        "title",
        "content_type",
        "copy_text",
        "asset_refs",
        "artist_id",
        "release_id",
        "owner_profile_id",
        "scheduled_at",
        "channels",
    }
    assert set(schemas["MarketingContentUpdateRequest"]["properties"]) == {
        "title",
        "content_type",
        "copy_text",
        "asset_refs",
        "artist_id",
        "release_id",
        "owner_profile_id",
        "scheduled_at",
        "channels",
    }
    assert "approved_at" in schemas["MarketingContentResponse"]["properties"]
    assert "approval_request_id" in schemas["MarketingContentResponse"]["properties"]
    assert "published_at" in schemas["MarketingContentResponse"]["properties"]


def test_approval_queue_routes_require_authentication(client: TestClient) -> None:
    response = client.get(f"/api/v1/workspaces/{uuid4()}/approvals")
    assert response.status_code == 401


def test_approval_queue_submission_listing_filters_pagination_and_detail(
    marketing_content_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededMarketingContentApi,
    ],
) -> None:
    client, _sessionmaker, seeded = marketing_content_client
    _set_context(client, seeded)
    first = client.post(
        _base(seeded), json=_draft_payload(seeded, title="First")
    ).json()
    second = client.post(
        _base(seeded, seeded.second_campaign_id),
        json={
            **_draft_payload(seeded, title="Second"),
            "artist_id": None,
            "release_id": None,
        },
    ).json()

    submitted = client.post(
        _approval_submit_base(seeded, first["id"]),
        json={"summary": "Ready", "metadata": {"source": "api-test"}},
    )
    assert submitted.status_code == 201
    approval_id = submitted.json()["id"]
    assert submitted.json()["resource_type"] == "marketing_content_item"
    assert submitted.json()["marketing_content_preview"]["title"] == "First"
    assert submitted.json()["submitted_revision"] == 1
    assert submitted.json()["is_stale"] is False

    client.post(
        _approval_submit_base(seeded, second["id"], seeded.second_campaign_id),
        json={},
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.approver_user_id,
        email="marketing-approver-profile@example.com",
        capability_permissions=(
            Capability.marketing_content_view.value,
            Capability.marketing_content_approve.value,
        ),
        department_access=("marketing",),
    )
    assigned = client.post(
        f"{_approvals_base(seeded)}/{approval_id}/assign",
        json={"assigned_profile_id": str(seeded.approver_profile_id)},
    )
    assert assigned.status_code == 200
    assert assigned.json()["stage_assignment"]["profile_id"] == str(
        seeded.approver_profile_id
    )

    list_response = client.get(
        _approvals_base(seeded),
        params={
            "status": "in_review",
            "resource_type": "marketing_content_item",
            "campaign_id": str(seeded.campaign_id),
            "artist_id": str(seeded.artist_id),
            "submitter_profile_id": str(seeded.owner_profile_id),
            "assigned_reviewer_profile_id": str(seeded.approver_profile_id),
            "assigned_to_me": "true",
            "limit": "1",
            "offset": "0",
        },
    )
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert list_response.json()["approvals"][0]["id"] == approval_id

    second_page = client.get(
        _approvals_base(seeded),
        params={"limit": "1", "offset": "1"},
    )
    assert second_page.status_code == 200
    assert second_page.json()["total"] == 2
    assert len(second_page.json()["approvals"]) == 1

    detail = client.get(f"{_approvals_base(seeded)}/{approval_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["campaign"] == {
        "id": str(seeded.campaign_id),
        "name": "Alpha Campaign",
    }
    assert body["artist"] == {"id": str(seeded.artist_id), "name": "Alpha Artist"}
    assert body["release"] == {"id": str(seeded.release_id), "name": "Alpha Single"}
    assert body["current_resource_revision"] == 1
    assert body["decision_history"][0]["decision"] == "submitted"
    assert body["available_actions"] == [
        "approved",
        "rejected",
        "changes_requested",
    ]

    _set_context(client, seeded)
    submitted_by_me = client.get(
        _approvals_base(seeded),
        params={"submitted_by_me": "true"},
    )
    assert submitted_by_me.status_code == 200
    assert submitted_by_me.json()["total"] == 2

    outside_scope = client.get(
        f"/api/v1/workspaces/{seeded.outside_workspace_id}/approvals/{approval_id}"
    )
    assert outside_scope.status_code in {403, 404}


def test_approval_queue_capabilities_and_error_mapping(
    marketing_content_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededMarketingContentApi,
    ],
) -> None:
    client, sessionmaker, seeded = marketing_content_client
    _set_context(client, seeded)
    created = client.post(_base(seeded), json=_draft_payload(seeded)).json()
    submitted = client.post(_approval_submit_base(seeded, created["id"]), json={})
    assert submitted.status_code == 201
    approval_id = submitted.json()["id"]

    asyncio.run(_set_viewer_capabilities(sessionmaker, seeded, ()))
    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        email="marketing-viewer@example.com",
        workspace_permission=WorkspacePermission.guest,
        capability_permissions=(),
        department_access=("marketing",),
    )
    assert client.get(_approvals_base(seeded)).status_code == 403

    asyncio.run(
        _set_viewer_capabilities(
            sessionmaker,
            seeded,
            (Capability.marketing_content_view.value,),
        )
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        email="marketing-viewer@example.com",
        workspace_permission=WorkspacePermission.guest,
        capability_permissions=(Capability.marketing_content_view.value,),
        department_access=("marketing",),
    )
    detail = client.get(f"{_approvals_base(seeded)}/{approval_id}")
    assert detail.status_code == 200
    assert detail.json()["available_actions"] == []
    assert (
        client.post(
            f"{_approvals_base(seeded)}/{approval_id}/decisions",
            json={"action": "approved"},
        ).status_code
        == 403
    )
    assert (
        client.get(
            _approvals_base(seeded), params={"resource_type": "unsupported"}
        ).status_code
        == 400
    )


def test_approval_queue_decisions_and_idempotency(
    marketing_content_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededMarketingContentApi,
    ],
) -> None:
    client, _sessionmaker, seeded = marketing_content_client

    def submit(title: str) -> str:
        _set_context(client, seeded)
        created = client.post(
            _base(seeded),
            json=_draft_payload(seeded, title=title),
        ).json()
        response = client.post(_approval_submit_base(seeded, created["id"]), json={})
        assert response.status_code == 201
        return response.json()["id"]

    def reviewer() -> None:
        _set_context(
            client,
            seeded,
            user_id=seeded.approver_user_id,
            email="marketing-approver-profile@example.com",
            capability_permissions=(
                Capability.marketing_content_view.value,
                Capability.marketing_content_approve.value,
            ),
            department_access=("marketing",),
        )

    approved_id = submit("Approve")
    reviewer()
    approved = client.post(
        f"{_approvals_base(seeded)}/{approved_id}/decisions",
        json={"action": "approved", "idempotency_key": "approve-once"},
    )
    repeated = client.post(
        f"{_approvals_base(seeded)}/{approved_id}/decisions",
        json={"action": "approved", "idempotency_key": "approve-once"},
    )
    duplicate_action = client.post(
        f"{_approvals_base(seeded)}/{approved_id}/decisions",
        json={"action": "rejected", "reason": "No", "idempotency_key": "other-key"},
    )
    assert approved.status_code == 200
    assert repeated.status_code == 200
    assert duplicate_action.status_code == 409

    rejected_id = submit("Reject")
    reviewer()
    rejected = client.post(
        f"{_approvals_base(seeded)}/{rejected_id}/decisions",
        json={"action": "rejected", "reason": "Off brief"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    changes_id = submit("Changes")
    reviewer()
    changes = client.post(
        f"{_approvals_base(seeded)}/{changes_id}/decisions",
        json={"action": "changes_requested", "reason": "Revise copy"},
    )
    assert changes.status_code == 200
    assert changes.json()["status"] == "changes_requested"

    cancelled_id = submit("Cancel")
    _set_context(client, seeded)
    cancelled = client.post(
        f"{_approvals_base(seeded)}/{cancelled_id}/decisions",
        json={"action": "cancelled", "reason": "Submitted by mistake"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    missing_reason = submit("Reason")
    reviewer()
    assert (
        client.post(
            f"{_approvals_base(seeded)}/{missing_reason}/decisions",
            json={"action": "rejected"},
        ).status_code
        == 422
    )


def test_approval_queue_self_agent_stale_duplicate_and_legacy_status_compatibility(
    marketing_content_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededMarketingContentApi,
    ],
) -> None:
    client, _sessionmaker, seeded = marketing_content_client
    _set_context(client, seeded)
    created = client.post(_base(seeded), json=_draft_payload(seeded)).json()
    approval_id = client.post(
        _approval_submit_base(seeded, created["id"]),
        json={},
    ).json()["id"]

    self_approval = client.post(
        f"{_approvals_base(seeded)}/{approval_id}/decisions",
        json={"action": "approved"},
    )
    assert self_approval.status_code == 409

    class AgentContext(CurrentUserContext):
        @property
        def authorization_actor(self):
            from labelos_api.authorization import ActorKind, AuthorizationActor

            return AuthorizationActor(
                kind=ActorKind.ai_agent,
                subject=f"agent_{self.user.id}",
                user_id=self.user.id,
            )

    async def override_agent_context() -> AgentContext:
        return AgentContext(
            user=User(id=seeded.approver_user_id, email="agent@example.com"),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject=f"user_{seeded.approver_user_id}",
                session_id="session_SECRET",
                email="agent@example.com",
                organization_id="org_ALPHA_MARKETING_CONTENT",
                role=WorkspacePermission.guest.value,
                roles=(WorkspacePermission.guest.value,),
            ),
            memberships=(
                MembershipContext(
                    organization_id=seeded.workspace_id,
                    organization_name="Alpha Label",
                    organization_slug="alpha-marketing-content-api",
                    workos_organization_id="org_ALPHA_MARKETING_CONTENT",
                    workspace_permission=WorkspacePermission.guest,
                    department_access=("marketing",),
                    capability_permissions=(
                        Capability.marketing_content_view.value,
                        Capability.marketing_content_approve.value,
                    ),
                ),
            ),
        )

    client.app.dependency_overrides[get_current_user_context] = override_agent_context
    agent_denial = client.post(
        f"{_approvals_base(seeded)}/{approval_id}/decisions",
        json={"action": "approved"},
    )
    assert agent_denial.status_code == 409

    _set_context(client, seeded)
    stale_content = client.post(
        _base(seeded),
        json=_draft_payload(seeded, title="Stale"),
    ).json()
    stale_id = client.post(
        _approval_submit_base(seeded, stale_content["id"]),
        json={},
    ).json()["id"]
    client.patch(
        f"{_base(seeded)}/{stale_content['id']}",
        json={"title": "Stale Edited"},
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.approver_user_id,
        email="marketing-approver-profile@example.com",
        capability_permissions=(
            Capability.marketing_content_view.value,
            Capability.marketing_content_approve.value,
        ),
        department_access=("marketing",),
    )
    stale_decision = client.post(
        f"{_approvals_base(seeded)}/{stale_id}/decisions",
        json={"action": "approved"},
    )
    assert stale_decision.status_code == 409
    assert (
        client.get(f"{_approvals_base(seeded)}/{stale_id}").json()["is_stale"] is True
    )

    _set_context(client, seeded)
    duplicate_content = client.post(
        _base(seeded),
        json=_draft_payload(seeded, title="Duplicate"),
    ).json()
    assert (
        client.post(
            _approval_submit_base(seeded, duplicate_content["id"]), json={}
        ).status_code
        == 201
    )
    assert (
        client.post(
            _approval_submit_base(seeded, duplicate_content["id"]), json={}
        ).status_code
        == 409
    )

    legacy_content = client.post(
        _base(seeded),
        json=_draft_payload(seeded, title="Legacy"),
    ).json()
    legacy_submit = client.patch(
        f"{_base(seeded)}/{legacy_content['id']}/status",
        json={"status": "in_review"},
    )
    assert legacy_submit.status_code == 200
    legacy_request_id = legacy_submit.json()["approval_request_id"]
    legacy_detail = client.get(f"{_approvals_base(seeded)}/{legacy_request_id}")
    assert legacy_detail.status_code == 200
    assert legacy_detail.json()["resource_id"] == legacy_content["id"]


def test_approval_queue_openapi_contract_exposes_stable_routes(
    marketing_content_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededMarketingContentApi,
    ],
) -> None:
    client, _sessionmaker, _seeded = marketing_content_client
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    schemas = schema["components"]["schemas"]

    assert "/api/v1/workspaces/{workspace_id}/approvals" in paths
    assert "/api/v1/workspaces/{workspace_id}/approvals/{approval_request_id}" in paths
    assert (
        "/api/v1/workspaces/{workspace_id}/approvals/{approval_request_id}/decisions"
        in paths
    )
    assert (
        "/api/v1/workspaces/{workspace_id}/approvals/{approval_request_id}/assign"
        in paths
    )
    assert (
        "/api/v1/workspaces/{workspace_id}/campaigns/{campaign_id}/marketing-content/{content_id}/approval-requests"
        in paths
    )
    assert set(schemas["ApprovalDecisionAction"]["enum"]) == {
        "approved",
        "rejected",
        "changes_requested",
        "cancelled",
    }
    assert "available_actions" in schemas["ApprovalRequestDetailResponse"]["properties"]
