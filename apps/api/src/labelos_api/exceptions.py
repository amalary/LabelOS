import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException

from labelos_api.models import ErrorResponse
from labelos_api.scheduling.timezones import ScheduleValidationError

logger = logging.getLogger(__name__)


class SchedulingAPIConflict(HTTPException):
    """Sanitized, machine-readable scheduling command rejection."""

    def __init__(self, reason_codes: list[str]):
        super().__init__(
            status_code=409,
            detail={"code": reason_codes[0], "reason_codes": reason_codes},
        )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SchedulingAPIConflict)
    async def scheduling_conflict_handler(
        request: Request, exc: SchedulingAPIConflict
    ) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(ScheduleValidationError)
    async def schedule_validation_exception_handler(
        request: Request, exc: ScheduleValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={**ErrorResponse(detail=str(exc)).model_dump(), "code": exc.code},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        logger.info(
            "HTTP exception",
            extra={"path": request.url.path, "status_code": exc.status_code},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(detail=str(exc.detail)).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.info("Validation error", extra={"path": request.url.path})
        if "scheduling" in getattr(request.scope.get("route"), "tags", []):
            # Never reflect caller input or Pydantic context (which may contain
            # exception objects, supplied account data, or arbitrary JSON).
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={
                    "detail": [
                        {
                            "type": error["type"],
                            "loc": list(error["loc"]),
                            "msg": error["msg"],
                        }
                        for error in exc.errors()
                    ]
                },
            )
        for error in exc.errors():
            if error["type"] in {"timestamp_timezone_required", "invalid_timestamp"}:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={
                        **ErrorResponse(detail=error["msg"]).model_dump(),
                        "code": error["type"],
                    },
                )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=ErrorResponse(detail="Request validation failed").model_dump(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled exception", extra={"path": request.url.path})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(detail="Internal server error").model_dump(),
        )
