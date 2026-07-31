from fastapi import FastAPI

from labelos_agents.config import get_settings
from labelos_agents.exceptions import register_exception_handlers
from labelos_agents.logging import configure_logging, request_logging_middleware
from labelos_agents.models import RootResponse
from labelos_agents.routes.health import router as health_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(
        settings.log_level,
        service_name=settings.service_name,
        service_version=settings.app_version,
        environment=settings.environment,
        log_format=settings.log_format,
    )

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
    )

    register_exception_handlers(app)
    app.middleware("http")(request_logging_middleware)

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
