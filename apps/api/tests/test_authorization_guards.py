from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from labelos_database.models import User, WorkspacePermission

from labelos_api.auth import (
    AuthenticatedPrincipal,
    CurrentUserContext,
    MembershipContext,
    get_current_user_context,
    get_session,
)
from labelos_api.authorization import (
    ActorKind,
    AuthorizationActor,
    AuthorizationDecision,
    AuthorizationResource,
    Capability,
    ResourceKind,
    authorization_service,
    require_capability,
)
from labelos_api.exceptions import register_exception_handlers


def _context(*, workspace_id=None) -> CurrentUserContext:
    workspace_id = workspace_id or uuid4()
    return CurrentUserContext(
        user=User(id=uuid4(), email="person@example.com", display_name="Person"),
        principal=AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01TEST",
            organization_id="org_01TEST",
            role="member",
            roles=("member",),
        ),
        memberships=(
            MembershipContext(
                organization_id=workspace_id,
                organization_name="Example Label",
                organization_slug="example-label",
                workos_organization_id="org_01TEST",
                workspace_permission=WorkspacePermission.member,
            ),
        ),
    )


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    async def override_session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = override_session

    @app.patch(
        "/workspaces/{workspace_id}/artist-profiles/{artist_profile_id}",
        dependencies=[
            Depends(
                require_capability(
                    "artist.profile.edit",
                    workspace_param="workspace_id",
                    resource_kind=ResourceKind.artist_profile,
                    resource_id_param="artist_profile_id",
                    department="a&r",
                    hide_resource_existence=True,
                )
            )
        ],
    )
    async def update_artist_profile() -> dict[str, bool]:
        return {"ok": True}

    @app.post(
        "/contracts",
        dependencies=[
            Depends(require_capability(Capability.contract_create, department="legal"))
        ],
    )
    async def create_contract() -> dict[str, bool]:
        return {"ok": True}

    return app


def _decision(*, allowed: bool, reason: str) -> AuthorizationDecision:
    return AuthorizationDecision(
        actor=AuthorizationActor(kind=ActorKind.user, subject="user_01TEST"),
        action=Capability.artist_profile_edit,
        workspace_id=None,
        resource=None,
        allowed=allowed,
        reason=reason,
    )


def test_require_capability_passes_workspace_and_resource_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    workspace_id = uuid4()
    resource_id = uuid4()
    app.dependency_overrides[get_current_user_context] = lambda: _context(
        workspace_id=workspace_id
    )
    calls = []

    async def decide_capability(session, *, actor, workspace, capability, resource):
        calls.append((session, actor, workspace, capability, resource))
        return _decision(allowed=True, reason="capability_allowed")

    monkeypatch.setattr(
        authorization_service,
        "decide_capability",
        decide_capability,
    )

    with TestClient(app) as client:
        response = client.patch(
            f"/workspaces/{workspace_id}/artist-profiles/{resource_id}"
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(calls) == 1
    _, actor, workspace, capability, resource = calls[0]
    assert isinstance(actor, CurrentUserContext)
    assert workspace == workspace_id
    assert capability == Capability.artist_profile_edit
    assert resource == AuthorizationResource(
        kind=ResourceKind.artist_profile,
        id=resource_id,
        department="a&r",
    )


def test_require_capability_returns_403_for_missing_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    app.dependency_overrides[get_current_user_context] = _context

    async def decide_capability(session, *, actor, workspace, capability, resource):
        return _decision(allowed=False, reason="missing_capability")

    monkeypatch.setattr(
        authorization_service,
        "decide_capability",
        decide_capability,
    )

    with TestClient(app) as client:
        response = client.post("/contracts")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_require_capability_returns_403_for_missing_department(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    app.dependency_overrides[get_current_user_context] = _context

    async def decide_capability(session, *, actor, workspace, capability, resource):
        return _decision(allowed=False, reason="insufficient_department_access")

    monkeypatch.setattr(
        authorization_service,
        "decide_capability",
        decide_capability,
    )

    with TestClient(app) as client:
        response = client.post("/contracts")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient department access"}


def test_require_capability_can_hide_resource_scope_failures_as_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    app.dependency_overrides[get_current_user_context] = _context

    async def decide_capability(session, *, actor, workspace, capability, resource):
        return _decision(allowed=False, reason="invalid_resource_scope")

    monkeypatch.setattr(
        authorization_service,
        "decide_capability",
        decide_capability,
    )

    with TestClient(app) as client:
        response = client.patch(f"/workspaces/{uuid4()}/artist-profiles/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_require_capability_returns_401_without_authentication() -> None:
    app = _app()

    with TestClient(app) as client:
        response = client.post("/contracts")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
