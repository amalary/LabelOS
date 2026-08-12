from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any
from urllib.parse import quote, urlencode

import httpx
from fastapi import Depends

from labelos_api.config import Settings, get_settings


class WorkOSAPIError(Exception):
    def __init__(self, status_code: int, message: str = "WorkOS API request failed"):
        super().__init__(message)
        self.status_code = status_code


class WorkOSClient:
    def __init__(self, *, api_key: str, base_url: str = "https://api.workos.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query, doseq=True)}"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.request(
                method,
                url,
                json=json_body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        if response.status_code >= 400:
            raise WorkOSAPIError(response.status_code)
        if response.status_code == 204:
            return {}
        return response.json()

    async def list_invitations(
        self,
        *,
        organization_id: str,
        email: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"organization_id": organization_id, "limit": limit}
        if email is not None:
            query["email"] = email
        response = await self._request(
            "GET",
            "/user_management/invitations",
            query=query,
        )
        return list(response.get("data") or [])

    async def send_invitation(
        self,
        *,
        email: str,
        organization_id: str,
        role_slug: str,
        inviter_user_id: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "email": email,
            "organization_id": organization_id,
            "role_slug": role_slug,
        }
        if inviter_user_id:
            body["inviter_user_id"] = inviter_user_id
        return await self._request(
            "POST",
            "/user_management/invitations",
            json_body=body,
        )

    async def find_invitation_by_token(self, token: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/user_management/invitations/by_token/{quote(token, safe='')}",
        )

    async def accept_invitation(self, invitation_id: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/user_management/invitations/{invitation_id}/accept",
        )

    async def list_organization_memberships(
        self,
        *,
        organization_id: str,
        user_id: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"organization_id": organization_id, "limit": limit}
        if user_id is not None:
            query["user_id"] = user_id
        if statuses:
            query["statuses[]"] = statuses
        response = await self._request(
            "GET",
            "/user_management/organization_memberships",
            query=query,
        )
        return list(response.get("data") or [])

    async def update_organization_membership(
        self,
        *,
        membership_id: str,
        role_slug: str,
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"/user_management/organization_memberships/{membership_id}",
            json_body={"role_slug": role_slug},
        )

    async def delete_organization_membership(self, membership_id: str) -> None:
        await self._request(
            "DELETE",
            f"/user_management/organization_memberships/{membership_id}",
        )


async def get_workos_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[WorkOSClient | None]:
    if not settings.workos_api_key:
        yield None
        return
    yield WorkOSClient(api_key=settings.workos_api_key)
