"""Trusted application composition; no receiver selection from human API input."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.config import Settings
from labelos_api.scheduling.contracts import (
    DeliveryAcceptanceRequest,
    PublishingDeliveryAcceptancePort,
    RetryableUnavailable,
)
from labelos_api.services.delivery_orchestrator import PublishingDeliveryReceiver


class UnavailableDeliveryReceiver:
    async def accept(
        self, session: AsyncSession, request: DeliveryAcceptanceRequest
    ) -> RetryableUnavailable:
        return RetryableUnavailable()


def configured_receiver(
    settings: Settings, *, workspace_id: UUID | None = None
) -> PublishingDeliveryAcceptancePort:
    settings.validate_delivery_receiver()
    if settings.delivery_receiver_backend == "publishing":
        scope = workspace_id or settings.scheduling_worker_workspace_id
        if not isinstance(scope, UUID):
            raise RuntimeError(
                "Publishing delivery receiver requires a workspace scope"
            )
        return PublishingDeliveryReceiver(scope)
    return UnavailableDeliveryReceiver()
