from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from labelos_api.auth import CurrentUserContext
from labelos_api.authorization import (
    Capability,
    Permission,
    require_capability,
    require_permission,
    require_role,
)

router = APIRouter(prefix="/authorization/examples", tags=["authorization"])


class ProtectedRouteResponse(BaseModel):
    ok: bool
    guard: str


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
    "/admin",
    response_model=ProtectedRouteResponse,
    summary="Example role-protected route",
)
async def admin_example(
    _context: Annotated[
        CurrentUserContext,
        Depends(require_role("admin")),
    ],
) -> ProtectedRouteResponse:
    return ProtectedRouteResponse(ok=True, guard="admin")


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
