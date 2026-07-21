from fastapi import APIRouter
from labelos_database.session import check_database_health

from labelos_api.config import get_settings
from labelos_api.models import DatabaseHealthResponse, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def read_health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/database", response_model=DatabaseHealthResponse)
async def read_database_health() -> DatabaseHealthResponse:
    settings = get_settings()
    healthy = await check_database_health(settings)
    return DatabaseHealthResponse(
        status="ok" if healthy else "error",
        database="ok" if healthy else "unavailable",
    )
