from fastapi import APIRouter

from labelos_agents.config import get_settings
from labelos_agents.models import HealthResponse, StatusResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def read_health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/api/v1/status", response_model=StatusResponse)
async def read_status() -> StatusResponse:
    settings = get_settings()
    return StatusResponse(
        service="agents",
        status="ok",
        environment=settings.environment,
        version=settings.app_version,
        model_provider=settings.model_provider,
    )
