from fastapi import APIRouter

from labelos_api.config import get_settings
from labelos_api.models import StatusResponse

router = APIRouter(tags=["status"])


@router.get("/status", response_model=StatusResponse)
async def read_status() -> StatusResponse:
    settings = get_settings()
    return StatusResponse(
        service="api",
        status="ok",
        environment=settings.environment,
        version=settings.app_version,
    )
