"""Fail-closed deployment wiring; successful receivers exist only in tests today."""

from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.config import Settings
from labelos_api.scheduling.contracts import (
    DeliveryAcceptanceRequest,
    RetryableUnavailable,
)


class UnavailableDeliveryReceiver:
    async def accept(
        self, session: AsyncSession, request: DeliveryAcceptanceRequest
    ) -> RetryableUnavailable:
        return RetryableUnavailable()


def configured_receiver(settings: Settings) -> UnavailableDeliveryReceiver:
    settings.validate_delivery_receiver()
    return UnavailableDeliveryReceiver()
