from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from labelos_api.auth import CurrentUserContext
from labelos_api.authorization import Permission, require_permission, require_role

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
