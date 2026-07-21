from fastapi import FastAPI

from labelos_agents.config import get_settings
from labelos_agents.logging import configure_logging
from labelos_agents.models import RootResponse
from labelos_agents.routes.health import router as health_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
    )

    @app.get("/", response_model=RootResponse, tags=["root"])
    async def read_root() -> RootResponse:
        return RootResponse(
            name=settings.app_name,
            environment=settings.environment,
            version=settings.app_version,
        )

    app.include_router(health_router)
    return app


app = create_app()
