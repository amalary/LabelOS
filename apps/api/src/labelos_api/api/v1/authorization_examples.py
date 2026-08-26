from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from labelos_api.auth import CurrentUserContext
from labelos_api.authorization import (
    Capability,
    Permission,
    has_capability,
    require_capability,
    require_organization,
    require_permission,
)

router = APIRouter(prefix="/authorization/examples", tags=["authorization"])


class ProtectedRouteResponse(BaseModel):
    ok: bool
    guard: str


def require_example_capability(required_capability: Capability):
    async def dependency(
        context: Annotated[CurrentUserContext, Depends(require_organization())],
    ) -> CurrentUserContext:
        if has_capability(context, required_capability):
            return context
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient capability permission",
        )

    return Depends(dependency)


@router.get(
    "/artists-manage",
    response_model=ProtectedRouteResponse,
    summary="Example permission-protected route",
)
async def manage_artists_example(
    _context: Annotated[
        CurrentUserContext,
        Depends(require_permission(Permission.artists_manage)),
    ],
) -> ProtectedRouteResponse:
    return ProtectedRouteResponse(ok=True, guard=Permission.artists_manage.value)


@router.get(
    "/workspace-administration",
    response_model=ProtectedRouteResponse,
    summary="Example capability-protected workspace administration route",
)
async def workspace_administration_example(
    _context: Annotated[
        CurrentUserContext,
        require_example_capability(Capability.workspace_update),
    ],
) -> ProtectedRouteResponse:
    return ProtectedRouteResponse(ok=True, guard=Capability.workspace_update.value)


@router.post(
    "/contracts",
    response_model=ProtectedRouteResponse,
    summary="Example capability-protected route",
)
async def create_contract_example(
    _context: Annotated[
        CurrentUserContext,
        Depends(require_capability(Capability.contract_create, department="legal")),
    ],
) -> ProtectedRouteResponse:
    return ProtectedRouteResponse(ok=True, guard=Capability.contract_create.value)
