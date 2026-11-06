import asyncio
import json

import httpx
import pytest
from labelos_database.models import AuthIdentity, OrganizationMembership
from labelos_database.workspace_memberships import (
    ensure_workspace_membership_for_organization_membership,
)
from sqlalchemy import select

from labelos_api.services import invited_workspace_activation as service
from test_organizations_api import _set_context, _set_joiner_context
from test_organizations_api import organizations_client as organizations_client


def remote_row(**changes):
    return {
        "id": "om_INVITED",
        "user_id": "user_JOINER",
        "organization_id": "org_ALPHA",
        "status": "active",
        "role": {"slug": "member"},
        **changes,
    }


@pytest.mark.parametrize("status", ["inactive", "pending"])
def test_remote_inactive_membership_is_never_reactivated(status):
    def handler(request):
        assert request.method == "GET"
        assert request.url.params["statuses"] == "active,inactive,pending"
        return httpx.Response(200, json={"data": [remote_row(status=status)]})

    async def run():
        async with httpx.AsyncClient(
            base_url="https://api.workos.com", transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(ValueError):
                await service.ensure_remote_membership(
                    client, user_id="user_JOINER", organization_id="org_ALPHA"
                )

    asyncio.run(run())


@pytest.mark.parametrize(
    "row",
    [
        remote_row(role={"slug": "owner"}),
        remote_row(roles=[{"slug": "member"}, {"slug": "admin"}]),
        remote_row(organization_id="org_FOREIGN"),
        remote_row(user_id="user_FOREIGN"),
    ],
)
def test_remote_mismatch_or_privileged_membership_is_not_adopted(row):
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"data": [row]})

    async def run():
        async with httpx.AsyncClient(
            base_url="https://api.workos.com", transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(ValueError):
                await service.ensure_remote_membership(
                    client, user_id="user_JOINER", organization_id="org_ALPHA"
                )

    asyncio.run(run())


def prepare_invited_member(configured):
    client, maker, seeded = configured
    _set_context(client, seeded)
    invite = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json={
            "email": "joiner@example.com",
            "workspace_roles": ["a_and_r"],
            "department_access": ["a&r"],
        },
    )
    assert invite.status_code == 201
    _set_joiner_context(client, seeded)
    accepted = client.post(
        f"/api/v1/organizations/invites/{invite.json()['token']}/accept", json={}
    )
    assert accepted.status_code == 200, accepted.text

    async def identity():
        async with maker() as session:
            owner = await session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == seeded.user_id,
                    OrganizationMembership.organization_id == seeded.org_a_id,
                )
            )
            await ensure_workspace_membership_for_organization_membership(
                session, owner
            )
            session.add(
                AuthIdentity(
                    user_id=seeded.joiner_id, provider="workos", subject="user_JOINER"
                )
            )
            await session.commit()

    asyncio.run(identity())
    return f"/api/v1/organizations/{seeded.org_a_id}/activate"


def test_accepted_invite_connects_once_as_member(organizations_client, monkeypatch):
    client, maker, seeded = organizations_client
    url = prepare_invited_member(organizations_client)
    monkeypatch.setenv("WORKOS_API_KEY", "synthetic-secret")
    from labelos_api.config import get_settings

    get_settings.cache_clear()
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(
                200, json={"data": [], "list_metadata": {"after": None}}
            )
        assert json.loads(request.content) == {
            "user_id": "user_JOINER",
            "organization_id": "org_ALPHA",
            "role_slug": "member",
        }
        return httpx.Response(201, json=remote_row())

    original = httpx.AsyncClient
    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    for _ in range(2):
        response = client.post(url)
        assert response.status_code == 200, response.text
        assert response.json()["organization"]["department_access"] == ["a&r"]
    assert calls == ["GET", "POST"]

    async def persisted():
        async with maker() as session:
            row = await session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == seeded.joiner_id
                )
            )
            assert row.workos_membership_id == "om_INVITED"
            assert row.workspace_permission.value == "member"

    asyncio.run(persisted())


def test_remote_failure_is_sanitized_and_not_marked_connected(
    organizations_client, monkeypatch
):
    client, maker, seeded = organizations_client
    url = prepare_invited_member(organizations_client)
    monkeypatch.setenv("WORKOS_API_KEY", "synthetic-secret")
    from labelos_api.config import get_settings

    get_settings.cache_clear()
    original = httpx.AsyncClient
    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, json={"secret": "DO_NOT_LEAK"})
            ),
        ),
    )
    response = client.post(url)
    assert response.status_code == 503
    assert "DO_NOT_LEAK" not in response.text

    async def persisted():
        async with maker() as session:
            row = await session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == seeded.joiner_id
                )
            )
            assert row.workos_membership_id is None

    asyncio.run(persisted())


def test_revoked_inviter_cannot_provision_membership(organizations_client, monkeypatch):
    client, maker, seeded = organizations_client
    url = prepare_invited_member(organizations_client)

    async def revoke():
        async with maker() as session:
            row = await session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == seeded.user_id,
                    OrganizationMembership.organization_id == seeded.org_a_id,
                )
            )
            row.status = "removed"
            await session.commit()

    asyncio.run(revoke())

    def forbidden_network(**kwargs):
        raise AssertionError("Revoked inviter must not provision WorkOS access")

    monkeypatch.setattr(service.httpx, "AsyncClient", forbidden_network)
    assert client.post(url).status_code == 403
