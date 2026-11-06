"""Connect an accepted local invitation before switching the WorkOS session."""

import httpx
from fastapi import HTTPException
from labelos_database.models import (
    AuthIdentity,
    UniversalProfile,
    WorkspaceMembership,
    WorkspacePermission,
)
from sqlalchemy import select

from labelos_api.authorization import Capability, authorization_service
from labelos_api.realtime import RealtimeEventType, RealtimePublisher


async def ensure_remote_membership(client, *, user_id, organization_id):
    """Never reactivate an inactive/pending grant or change an existing role."""
    params = {
        "user_id": user_id,
        "organization_id": organization_id,
        "statuses": "active,inactive,pending",
        "limit": 100,
    }
    response = await client.get(
        "/user_management/organization_memberships", params=params
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Invalid remote membership list")
    rows = payload["data"]
    if payload.get("list_metadata", {}).get("after") or len(rows) > 1:
        raise ValueError("Ambiguous remote membership")
    if rows:
        row = rows[0]
    else:
        response = await client.post(
            "/user_management/organization_memberships",
            json={
                "user_id": user_id,
                "organization_id": organization_id,
                "role_slug": "member",
            },
        )
        response.raise_for_status()
        row = response.json()
    if not isinstance(row, dict) or not isinstance(row.get("role"), dict):
        raise ValueError("Invalid remote membership")
    roles = row.get("roles", [row["role"]])
    if not isinstance(roles, list) or any(
        not isinstance(role, dict) or role.get("slug") != "member" for role in roles
    ):
        raise ValueError("Remote membership requires owner review")
    if (
        row.get("user_id") != user_id
        or row.get("organization_id") != organization_id
        or row.get("status") != "active"
        or row.get("role", {}).get("slug") != "member"
        or not isinstance(row.get("id"), str)
        or not row["id"].startswith("om_")
    ):
        raise ValueError("Remote membership not eligible")
    return row["id"]


async def connect_accepted_invitation(
    session, *, organization, membership, actor, settings
):
    # Serialize first-time switches, and remember the remote ID so deletion at
    # WorkOS can never cause this route to silently recreate a linked membership.
    await session.refresh(
        membership,
        ["status", "workos_membership_id", "workspace_permission"],
        with_for_update=True,
    )
    if membership.status != "active":
        raise HTTPException(403, "Workspace membership is not active")
    if membership.workos_membership_id:
        return
    local = await session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.organization_membership_id == membership.id,
            WorkspaceMembership.workspace_id == organization.id,
            WorkspaceMembership.status == "active",
        )
    )
    if local is None or local.invited_by is None:
        return
    if membership.workspace_permission != WorkspacePermission.member:
        raise HTTPException(409, "Invited membership requires owner review")
    inviter = await session.scalar(
        select(UniversalProfile).where(UniversalProfile.id == local.invited_by)
    )
    if inviter is None or not await authorization_service.has_capability(
        session,
        actor=inviter.user_id,
        workspace=organization.id,
        capability=Capability.workspace_member_invite,
    ):
        raise HTTPException(403, "Invitation approver no longer has access")
    identity = await session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.user_id == actor.id,
            AuthIdentity.provider == "workos",
        )
    )
    if identity is None or membership.user_id != actor.id:
        raise HTTPException(403, "Verified WorkOS identity required")
    if not settings.workos_api_key:
        raise HTTPException(503, "Workspace connection is not configured")
    try:
        async with httpx.AsyncClient(
            base_url="https://api.workos.com",
            timeout=15,
            headers={"Authorization": "Bearer " + settings.workos_api_key},
        ) as client:
            remote_id = await ensure_remote_membership(
                client,
                user_id=identity.subject,
                organization_id=organization.workos_organization_id,
            )
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(
            503,
            "Could not connect workspace membership; ask the owner to review access",
        ) from None
    membership.workos_membership_id = remote_id
    await RealtimePublisher(session).publish(
        organization_id=organization.id,
        event_type=RealtimeEventType.profile_membership_updated,
        actor=actor,
        entity_type="profile",
        entity_id=local.profile_id,
        payload={
            "profileId": str(local.profile_id),
            "membershipId": str(membership.id),
            "workspaceId": str(organization.id),
            "status": "active",
            "action": "workos_membership_connected",
        },
    )
    await session.commit()
