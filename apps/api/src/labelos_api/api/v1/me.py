from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from labelos_database.models import MembershipRole
from pydantic import BaseModel

from labelos_api.auth import CurrentUserContext, get_current_user_context

router = APIRouter(tags=["auth"])


class MeMembershipResponse(BaseModel):
    organization_id: UUID
    organization_name: str
    organization_slug: str
    role: MembershipRole


class MeResponse(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    auth_provider: str
    auth_subject: str
    memberships: list[MeMembershipResponse]


@router.get("/me", response_model=MeResponse)
async def read_me(
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> MeResponse:
    return MeResponse(
        id=context.user.id,
        email=context.user.email,
        display_name=context.user.display_name,
        auth_provider=context.principal.provider,
        auth_subject=context.principal.subject,
        memberships=[
            MeMembershipResponse(
                organization_id=membership.organization_id,
                organization_name=membership.organization_name,
                organization_slug=membership.organization_slug,
                role=membership.role,
            )
            for membership in context.memberships
        ],
    )
