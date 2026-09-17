"""Private Cloud Run app / explicit local CLI for a single bounded workspace sweep.

Run with uvicorn labelos_api.scheduling_worker:create_worker_app --factory.
This app is never mounted in labelos_api.main's user-facing API.
"""

import argparse
import asyncio
import logging
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from labelos_database.scheduling import SchedulingBlockedReason
from labelos_database.session import get_sessionmaker, reset_engine

from labelos_api.config import Settings, get_settings
from labelos_api.logging import configure_logging, request_logging_middleware
from labelos_api.scheduling.contracts import SchedulingFeatureControls
from labelos_api.scheduling.receivers import (
    UnavailableDeliveryReceiver,
    configured_receiver,
)
from labelos_api.scheduling.worker_auth import (
    authenticate_worker,
    validate_worker_settings,
)
from labelos_api.services.scheduling_processor import (
    SchedulingDueJobProcessor,
    SchedulingExecutionRefused,
    SchedulingWorker,
)

logger = logging.getLogger(__name__)
WORKER_PATH = "/internal/scheduling/run-due"
SAFE_OUTCOMES = {reason.value for reason in SchedulingBlockedReason} | {
    "handed_off",
    "execution_refused",
    "claim_lost",
    "job_failed",
    "delivery_unavailable",
}


async def run_sweep(
    settings: Settings, worker: SchedulingWorker, correlation_id: str
) -> JSONResponse:
    """Only called after OIDC verification or the guarded local command boundary."""
    # None is never a principal. Nor does actor=None in audit/outbox grant access.
    if not isinstance(worker, SchedulingWorker):
        raise TypeError("Authenticated SchedulingWorker required")
    assert settings.scheduling_worker_workspace_id is not None
    worker.require_workspace(settings.scheduling_worker_workspace_id)
    payload: dict[str, object] = {
        "correlation_id": correlation_id,
        "worker_id": worker.worker_id,
    }
    status_code = 200
    try:
        if not settings.scheduling_execution_enabled:
            payload["status"] = "execution_disabled"
        else:
            receiver = configured_receiver(settings)
            if isinstance(receiver, UnavailableDeliveryReceiver):
                payload["status"] = "receiver_unavailable"
                status_code = 503
            else:
                processor = SchedulingDueJobProcessor(
                    get_sessionmaker(settings),
                    worker=worker,
                    controls=SchedulingFeatureControls(
                        execution_enabled=True, delivery_receiver_configured=True
                    ),
                    receiver=receiver,
                    lateness_window_seconds=settings.scheduling_worker_lateness_seconds,
                    batch_size=settings.scheduling_worker_batch_size,
                    lease_duration=timedelta(
                        seconds=settings.scheduling_worker_lease_seconds
                    ),
                )
                # Cancellation unwinds the current DB transaction. Completed commits
                # remain durable; outstanding claims recover after their leases.
                async with asyncio.timeout(settings.scheduling_worker_timeout_seconds):
                    result = await processor.run(
                        settings.scheduling_worker_workspace_id
                    )
                outcomes: dict[str, int] = {}
                for key, count in result.outcomes.items():
                    safe_key = key if key in SAFE_OUTCOMES else "job_failed"
                    outcomes[safe_key] = outcomes.get(safe_key, 0) + count
                payload.update(
                    status="completed",
                    claimed=result.claimed,
                    recovered=result.recovered,
                    outcomes=outcomes,
                )
    except SchedulingExecutionRefused:
        payload["status"] = "execution_refused"
    except TimeoutError:
        payload["status"] = "timed_out"
        status_code = 504
    except Exception:
        # No exception text, SQL parameters, request content or stack traces.
        payload["status"] = "failed"
        status_code = 503
    logger.info("scheduling_worker_sweep", extra=payload)
    return JSONResponse(payload, status_code=status_code)


def create_worker_app() -> FastAPI:
    settings = get_settings()
    validate_worker_settings(settings)
    configure_logging(
        settings.log_level,
        service_name="labelos-scheduling-worker",
        service_version=settings.app_version,
        environment=settings.environment,
        log_format=settings.log_format,
    )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.middleware("http")(request_logging_middleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post(WORKER_PATH)
    async def run_due(request: Request):
        worker = await authenticate_worker(request, settings)
        # There is no request DTO: scope, identity and limits come from deployment.
        # Do not read or reflect arbitrary bodies (including actor/workspace fields).
        return await run_sweep(settings, worker, request.state.request_id)

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One local scheduling sweep")
    parser.add_argument("--execute", action="store_true", required=True)
    parser.parse_args(argv)
    settings = get_settings()
    validate_worker_settings(settings, local_cli=True)
    assert settings.scheduling_worker_workspace_id is not None
    worker = SchedulingWorker(
        principal_id=uuid5(NAMESPACE_URL, "labelos:scheduling:local-cli"),
        instance_id=uuid4(),
        workspace_ids=frozenset({settings.scheduling_worker_workspace_id}),
    )

    async def run():
        try:
            return await run_sweep(settings, worker, str(uuid4()))
        finally:
            await reset_engine()

    response = asyncio.run(run())
    print(bytes(response.body).decode())
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
