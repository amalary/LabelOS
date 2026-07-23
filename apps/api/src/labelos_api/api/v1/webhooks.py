from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from labelos_api.auth import SessionDep, SettingsDep
from labelos_api.workos_webhooks import (
    WorkOSWebhookPayloadError,
    WorkOSWebhookSignatureError,
    process_workos_webhook_event,
    verify_workos_webhook_signature,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookAcceptedResponse(BaseModel):
    ok: bool
    status: str


@router.post(
    "/workos",
    response_model=WebhookAcceptedResponse,
    summary="Receive WorkOS webhook events",
)
async def receive_workos_webhook(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> WebhookAcceptedResponse:
    if not settings.workos_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WorkOS webhooks are not configured",
        )

    raw_body = await request.body()
    signature_header = request.headers.get("workos-signature")
    try:
        verify_workos_webhook_signature(
            raw_body=raw_body,
            signature_header=signature_header,
            secret=settings.workos_webhook_secret,
        )
    except WorkOSWebhookSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid WorkOS webhook signature",
        ) from exc

    try:
        result = await process_workos_webhook_event(session=session, raw_body=raw_body)
    except WorkOSWebhookPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid WorkOS webhook payload",
        ) from exc

    return WebhookAcceptedResponse(ok=True, status=result.status)
