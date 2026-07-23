from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from labelos_api.auth import AuthenticatedPrincipal, get_current_principal

router = APIRouter(tags=["auth"])


class MeResponse(BaseModel):
    workos_user_id: str = Field(
        description="WorkOS user identifier from the validated bearer token.",
        examples=["user_01H9Z5P8K3N7M2Q4R6S8T0V1W2"],
    )
    organization_id: str | None = Field(
        default=None,
        description="Active WorkOS organization identifier when present on the token.",
        examples=["org_01H9Z5P8K3N7M2Q4R6S8T0V1W2"],
    )
    role: str | None = Field(
        default=None,
        description="WorkOS organization role included in the token, if any.",
        examples=["admin"],
    )
    permissions: list[str] = Field(
        default_factory=list,
        description="Application permissions included in the validated WorkOS token.",
        examples=[["artists:read", "artists:write"]],
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Get current authenticated user",
    description=(
        "Returns the safe application identity from the validated WorkOS bearer token. "
        "Secrets and raw token values are never returned."
    ),
    responses={
        401: {
            "description": "Missing, expired, or invalid WorkOS bearer token.",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_token": {
                            "summary": "Missing bearer token",
                            "value": {"detail": "Authentication required"},
                        },
                        "invalid_token": {
                            "summary": "Invalid bearer token",
                            "value": {"detail": "Invalid authentication token"},
                        },
                    }
                }
            },
        }
    },
)
async def read_me(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> MeResponse:
    return MeResponse(
        workos_user_id=principal.subject,
        organization_id=principal.organization_id,
        role=principal.role,
        permissions=list(principal.permissions),
    )
