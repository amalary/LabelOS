"""Bounded, authenticated uploads; attaching references uses normal draft edits."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from labelos_api.api.v1.marketing_content import _service_error
from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.scheduling.payload import MAX_ASSET_BYTES, InvalidHandoffPayload
from labelos_api.services.marketing_content_service import (
    MarketingContentAuthorizationError,
    MarketingContentNotFoundError,
)
from labelos_api.services.marketing_media import (
    MEDIA_TYPE,
    authorize_upload,
    store_asset,
)

router = APIRouter(prefix="/workspaces", tags=["marketing-content"])


@router.post("/{workspace_id}/marketing-content/{content_item_id}/assets")
async def upload_asset(
    workspace_id: UUID,
    content_item_id: UUID,
    request: Request,
    session: SessionDep,
    actor: Annotated[CurrentUserContext, Depends(get_current_user_context)],
):
    try:
        await authorize_upload(session, workspace_id, content_item_id, actor)
        # Do not retain a DB transaction/connection while receiving client bytes.
        await session.commit()
        media_type = request.headers.get("content-type", "").lower()
        if not MEDIA_TYPE.fullmatch(media_type):
            raise HTTPException(415, detail="Use an image, video or audio media type")
        length = request.headers.get("content-length")
        if length is not None:
            try:
                declared = int(length)
            except ValueError:
                raise HTTPException(400, detail="Invalid content length") from None
            if not 0 < declared <= MAX_ASSET_BYTES:
                raise HTTPException(
                    413, detail="Media must be between 1 byte and 16 MiB"
                )
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_ASSET_BYTES:
                raise HTTPException(413, detail="Media exceeds 16 MiB")
            data.extend(chunk)
        if not data:
            raise HTTPException(400, detail="Media is empty")
        reference = await store_asset(
            session,
            workspace_id,
            content_item_id,
            actor,
            bytes(data),
            media_type,
        )
        await session.commit()
        return reference
    except (MarketingContentAuthorizationError, MarketingContentNotFoundError) as exc:
        await session.rollback()
        _service_error(exc)
    except InvalidHandoffPayload:
        await session.rollback()
        raise HTTPException(
            409, detail="Media does not match its stored reference"
        ) from None
    except SQLAlchemyError:
        # Database exception parameters may include raw uploaded media. Keep them
        # out of the generic exception logger and the client response.
        await session.rollback()
        raise HTTPException(503, detail="Media storage unavailable") from None
