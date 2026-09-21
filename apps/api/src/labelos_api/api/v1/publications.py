"""Workspace-scoped publication inspection and human resolution commands."""

import base64
import hashlib
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.api.v1.marketing_content import _raise_capability_denial
from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.repositories.publishing import PublicationConflict
from labelos_api.services import marketing_content_service as content
from labelos_api.services.delivery_orchestrator import DeliveryIneligible
from labelos_api.services.publication_recovery import (
    PublicationHumanRequired,
    PublicationRecoveryService,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/publications", tags=["publications"]
)
Actor = Annotated[CurrentUserContext, Depends(get_current_user_context)]
OperationKey = Annotated[UUID, Header(alias="Idempotency-Key")]


async def recovery_session(session: SessionDep):
    try:
        yield session
    except content.MarketingContentAuthorizationError as exc:
        await session.rollback()
        _raise_capability_denial(exc.reason)
    except PublicationHumanRequired as exc:
        await session.rollback()
        raise HTTPException(403, detail="Human authorization required") from exc
    except content.MarketingContentNotFoundError as exc:
        await session.rollback()
        raise HTTPException(404, detail="Not found") from exc
    except (PublicationConflict, DeliveryIneligible, IntegrityError) as exc:
        await session.rollback()
        raise HTTPException(
            409, detail={"code": "publication_recovery_conflict"}
        ) from exc
    except BaseException:
        await session.rollback()
        raise


Session = Annotated[AsyncSession, Depends(recovery_session)]


class RecoveryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, strict=True)
    expected_action_version: int = Field(ge=0, strict=True)


class ManualCompletion(RecoveryCommand):
    # Explicit attestation; an optional URL alone is not a completion command.
    delivery_confirmed: bool = Field(strict=True)
    external_post_id: str | None = Field(default=None, min_length=1, max_length=512)
    provider_url: str | None = Field(default=None, min_length=1, max_length=2048)


@router.get("")
async def list_publications(
    workspace_id: UUID,
    session: Session,
    context: Actor,
    content_item_id: UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    after_id: UUID | None = None,
):
    from labelos_api.services.publication_history import list_publications as history

    return await history(
        session, workspace_id, content_item_id, context, limit=limit, after_id=after_id
    )


@router.get("/{publication_id}")
async def get_publication(
    workspace_id: UUID, publication_id: UUID, session: Session, context: Actor
):
    service = PublicationRecoveryService(session, workspace_id, actor=context)
    return await service.handoff(await service.get(publication_id))


@router.get("/{publication_id}/assets/{sha256}")
async def download_prepared_asset(
    workspace_id: UUID,
    publication_id: UUID,
    sha256: str,
    session: Session,
    context: Actor,
):
    service = PublicationRecoveryService(session, workspace_id, actor=context)
    row = await service.get(publication_id)
    for asset in json.loads(row.canonical_envelope)["content"]["asset_refs"]:
        if asset["sha256"] == sha256:
            data = base64.b64decode(asset["content_base64"], validate=True)
            if hashlib.sha256(data).hexdigest() != sha256:
                raise PublicationConflict("asset_integrity_failure")
            return Response(
                data,
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": f'attachment; filename="{sha256}"',
                    "X-Content-Type-Options": "nosniff",
                    "Cache-Control": "private, no-store",
                },
            )
    raise HTTPException(404, detail="Not found")


async def _command(
    workspace_id, publication_id, session, context, operation_id, payload, operation
):
    service = PublicationRecoveryService(session, workspace_id, actor=context)
    values = payload.model_dump(exclude={"delivery_confirmed"})
    if isinstance(payload, ManualCompletion) and not payload.delivery_confirmed:
        raise PublicationConflict("manual_confirmation_required")
    row = await service.command(
        publication_id, operation=operation, operation_id=operation_id, **values
    )
    response = await service.handoff(row)
    await session.commit()
    return response


@router.post("/{publication_id}/manual/start")
async def begin_manual(
    workspace_id: UUID,
    publication_id: UUID,
    payload: RecoveryCommand,
    session: Session,
    context: Actor,
    idempotency_key: OperationKey,
):
    return await _command(
        workspace_id,
        publication_id,
        session,
        context,
        idempotency_key,
        payload,
        "begin_manual",
    )


@router.post("/{publication_id}/manual/complete")
async def complete_manual(
    workspace_id: UUID,
    publication_id: UUID,
    payload: ManualCompletion,
    session: Session,
    context: Actor,
    idempotency_key: OperationKey,
):
    return await _command(
        workspace_id,
        publication_id,
        session,
        context,
        idempotency_key,
        payload,
        "complete_manual",
    )


@router.post("/{publication_id}/recover")
async def authorize_retry(
    workspace_id: UUID,
    publication_id: UUID,
    payload: RecoveryCommand,
    session: Session,
    context: Actor,
    idempotency_key: OperationKey,
):
    return await _command(
        workspace_id,
        publication_id,
        session,
        context,
        idempotency_key,
        payload,
        "authorize_retry",
    )
