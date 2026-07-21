from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from labelos_api.api.router import api_router
from labelos_api.config import get_settings
from labelos_api.exceptions import register_exception_handlers
from labelos_api.logging import configure_logging
from labelos_api.models import RootResponse
from labelos_api.routes.health import router as health_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_frontend_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    @app.get("/", response_model=RootResponse, tags=["root"])
    async def read_root() -> RootResponse:
        return RootResponse(
            name=settings.app_name,
            environment=settings.environment,
            version=settings.app_version,
        )

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
