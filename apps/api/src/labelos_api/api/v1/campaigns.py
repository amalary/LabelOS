from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from labelos_database.models import (
    Campaign,
    CampaignArtist,
    CampaignMember,
    CampaignRelease,
    CampaignStatus,
    CampaignType,
    WorkspaceMembership,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.authorization import (
    AuthorizationResource,
    Capability,
    ResourceKind,
    authorization_service,
)
from labelos_api.services import campaign_service
from labelos_api.services.campaign_service import (
    CampaignCreate,
    CampaignLifecycleError,
    CampaignNotFoundError,
    CampaignRelationshipError,
    CampaignUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["campaigns"])


class CampaignCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    campaign_type: CampaignType = CampaignType.other
    status: CampaignStatus = CampaignStatus.draft
    start_date: date | None = None
    target_end_date: date | None = None
    owner_profile_id: UUID | None = None
    primary_artist_id: UUID | None = None
    release_id: UUID | None = None


class CampaignUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    campaign_type: CampaignType | None = None
    start_date: date | None = None
    target_end_date: date | None = None
    owner_profile_id: UUID | None = None
    primary_artist_id: UUID | None = None
    release_id: UUID | None = None

    @model_validator(mode="after")
    def require_update(self) -> "CampaignUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one campaign field is required")
        return self


class CampaignStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CampaignStatus


class CampaignMemberUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_membership_id: UUID
    participation_status: str = Field(default="active", min_length=1, max_length=60)


class CampaignArtistUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artist_id: UUID
    relationship_kind: str = Field(default="collaborator", min_length=1, max_length=60)
    sort_order: int = Field(default=0, ge=0)


class CampaignReleaseUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: UUID
    relationship_kind: str = Field(default="related", min_length=1, max_length=60)


class CampaignArtistSummaryResponse(BaseModel):
    id: UUID
    name: str


class CampaignReleaseSummaryResponse(BaseModel):
    id: UUID
    title: str
    artist_id: UUID | None


class CampaignMemberSummaryResponse(BaseModel):
    workspace_membership_id: UUID
    profile_id: UUID
    display_name: str | None
    participation_status: str


class CampaignArtistRelationshipResponse(BaseModel):
    artist: CampaignArtistSummaryResponse
    relationship_kind: str
    sort_order: int


class CampaignReleaseRelationshipResponse(BaseModel):
    release: CampaignReleaseSummaryResponse
    relationship_kind: str


class CampaignResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    description: str | None
    campaign_type: CampaignType
    status: CampaignStatus
    start_date: date | None
    target_end_date: date | None
    created_by_user_id: UUID | None
    created_by_profile_id: UUID | None
    owner_profile_id: UUID | None
    primary_artist: CampaignArtistSummaryResponse | None
    release: CampaignReleaseSummaryResponse | None
    members: list[CampaignMemberSummaryResponse] = Field(default_factory=list)
    artists: list[CampaignArtistRelationshipResponse] = Field(default_factory=list)
    releases: list[CampaignReleaseRelationshipResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CampaignsListResponse(BaseModel):
    campaigns: list[CampaignResponse]
    total: int


class CampaignMembersListResponse(BaseModel):
    members: list[CampaignMemberSummaryResponse]


class CampaignArtistsListResponse(BaseModel):
    artists: list[CampaignArtistRelationshipResponse]


class CampaignReleasesListResponse(BaseModel):
    releases: list[CampaignReleaseRelationshipResponse]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _raise_capability_denial(reason: str) -> None:
    if reason in {"invalid_resource_scope", "membership_not_found"}:
        raise _not_found()
    if reason == "insufficient_department_access":
        raise _forbidden("Insufficient department access")
    raise _forbidden("Insufficient capability permission")


async def _require_campaign_capability(
    session: AsyncSession,
    *,
    context: CurrentUserContext,
    workspace_id: UUID,
    capability: Capability,
) -> None:
    decision = await authorization_service.decide_capability(
        session,
        actor=context,
        workspace=workspace_id,
        capability=capability,
        resource=AuthorizationResource(
            kind=ResourceKind.workspace,
            id=workspace_id,
            workspace_id=workspace_id,
        ),
    )
    if decision.allowed:
        return
    _raise_capability_denial(decision.reason)


async def _current_workspace_membership(
    session: AsyncSession,
    *,
    context: CurrentUserContext,
    workspace_id: UUID,
) -> WorkspaceMembership | None:
    return await session.scalar(
        select(WorkspaceMembership)
        .join(WorkspaceMembership.profile)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.status == "active")
        .where(WorkspaceMembership.profile.has(user_id=context.user.id))
    )


def _service_error(exc: CampaignNotFoundError | CampaignRelationshipError) -> None:
    if isinstance(exc, CampaignNotFoundError):
        raise _not_found() from exc
    raise _bad_request(str(exc)) from exc


def _artist_summary(artist) -> CampaignArtistSummaryResponse | None:
    if artist is None:
        return None
    return CampaignArtistSummaryResponse(id=artist.id, name=artist.name)


def _release_summary(release) -> CampaignReleaseSummaryResponse | None:
    if release is None:
        return None
    return CampaignReleaseSummaryResponse(
        id=release.id,
        title=release.title,
        artist_id=release.artist_id,
    )


def _member_response(link: CampaignMember) -> CampaignMemberSummaryResponse:
    membership = link.workspace_membership
    profile = membership.profile
    return CampaignMemberSummaryResponse(
        workspace_membership_id=membership.id,
        profile_id=membership.profile_id,
        display_name=profile.display_name,
        participation_status=link.participation_status,
    )


def _artist_link_response(link: CampaignArtist) -> CampaignArtistRelationshipResponse:
    return CampaignArtistRelationshipResponse(
        artist=CampaignArtistSummaryResponse(id=link.artist.id, name=link.artist.name),
        relationship_kind=link.relationship_kind,
        sort_order=link.sort_order,
    )


def _release_link_response(
    link: CampaignRelease,
) -> CampaignReleaseRelationshipResponse:
    return CampaignReleaseRelationshipResponse(
        release=CampaignReleaseSummaryResponse(
            id=link.release.id,
            title=link.release.title,
            artist_id=link.release.artist_id,
        ),
        relationship_kind=link.relationship_kind,
    )


def _campaign_response(campaign: Campaign) -> CampaignResponse:
    return CampaignResponse(
        id=campaign.id,
        workspace_id=campaign.organization_id,
        name=campaign.name,
        description=campaign.description,
        campaign_type=campaign.campaign_type,
        status=campaign.status,
        start_date=campaign.start_date,
        target_end_date=campaign.target_end_date,
        created_by_user_id=campaign.created_by_user_id,
        created_by_profile_id=campaign.created_by_profile_id,
        owner_profile_id=campaign.owner_profile_id,
        primary_artist=_artist_summary(campaign.primary_artist),
        release=_release_summary(campaign.release),
        members=[_member_response(link) for link in campaign.member_links],
        artists=[_artist_link_response(link) for link in campaign.artist_links],
        releases=[_release_link_response(link) for link in campaign.release_links],
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


async def _load_campaign_response(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    campaign_id: UUID,
) -> CampaignResponse:
    return _campaign_response(
        await campaign_service.get_campaign_by_id(session, workspace_id, campaign_id)
    )


@router.get(
    "/{workspace_id}/campaigns",
    response_model=CampaignsListResponse,
)
async def list_campaigns(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> CampaignsListResponse:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
    )
    campaigns = await campaign_service.list_workspace_campaigns(session, workspace_id)
    return CampaignsListResponse(
        campaigns=[_campaign_response(campaign) for campaign in campaigns],
        total=len(campaigns),
    )


@router.post(
    "/{workspace_id}/campaigns",
    response_model=CampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_campaign(
    workspace_id: UUID,
    payload: CampaignCreateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> CampaignResponse:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_create,
    )
    membership = await _current_workspace_membership(
        session,
        context=context,
        workspace_id=workspace_id,
    )
    if membership is None:
        raise _not_found()
    try:
        campaign = await campaign_service.create_campaign(
            session,
            workspace_id,
            CampaignCreate(
                **payload.model_dump(),
                created_by_user_id=context.user.id,
                created_by_profile_id=membership.profile_id,
            ),
        )
    except CampaignRelationshipError as exc:
        _service_error(exc)
    return await _load_campaign_response(
        session,
        workspace_id=workspace_id,
        campaign_id=campaign.id,
    )


@router.get(
    "/{workspace_id}/campaigns/{campaign_id}",
    response_model=CampaignResponse,
)
async def get_campaign(
    workspace_id: UUID,
    campaign_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> CampaignResponse:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
    )
    try:
        campaign = await campaign_service.get_campaign_by_id(
            session,
            workspace_id,
            campaign_id,
        )
    except CampaignNotFoundError as exc:
        _service_error(exc)
    return _campaign_response(campaign)


@router.patch(
    "/{workspace_id}/campaigns/{campaign_id}",
    response_model=CampaignResponse,
)
async def update_campaign(
    workspace_id: UUID,
    campaign_id: UUID,
    payload: CampaignUpdateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> CampaignResponse:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
    )
    try:
        campaign = await campaign_service.update_campaign(
            session,
            workspace_id,
            campaign_id,
            CampaignUpdate(**payload.model_dump(exclude_unset=True)),
        )
    except (CampaignNotFoundError, CampaignRelationshipError) as exc:
        _service_error(exc)
    return await _load_campaign_response(
        session,
        workspace_id=workspace_id,
        campaign_id=campaign.id,
    )


@router.patch(
    "/{workspace_id}/campaigns/{campaign_id}/status",
    response_model=CampaignResponse,
)
async def update_campaign_status(
    workspace_id: UUID,
    campaign_id: UUID,
    payload: CampaignStatusUpdateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> CampaignResponse:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_approve,
    )
    try:
        campaign = await campaign_service.change_campaign_status(
            session,
            workspace_id,
            campaign_id,
            payload.status,
        )
    except CampaignNotFoundError as exc:
        _service_error(exc)
    except CampaignLifecycleError as exc:
        raise _conflict(str(exc)) from exc
    return await _load_campaign_response(
        session,
        workspace_id=workspace_id,
        campaign_id=campaign.id,
    )


@router.post(
    "/{workspace_id}/campaigns/{campaign_id}/archive",
    response_model=CampaignResponse,
)
async def archive_campaign(
    workspace_id: UUID,
    campaign_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> CampaignResponse:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
    )
    try:
        campaign = await campaign_service.archive_campaign(
            session,
            workspace_id,
            campaign_id,
        )
    except CampaignNotFoundError as exc:
        _service_error(exc)
    except CampaignLifecycleError as exc:
        raise _conflict(str(exc)) from exc
    return await _load_campaign_response(
        session,
        workspace_id=workspace_id,
        campaign_id=campaign.id,
    )


@router.get(
    "/{workspace_id}/campaigns/{campaign_id}/members",
    response_model=CampaignMembersListResponse,
)
async def list_campaign_members(
    workspace_id: UUID,
    campaign_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> CampaignMembersListResponse:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
    )
    try:
        links = await campaign_service.list_campaign_members(
            session,
            workspace_id,
            campaign_id,
        )
    except CampaignNotFoundError as exc:
        _service_error(exc)
    return CampaignMembersListResponse(
        members=[_member_response(link) for link in links]
    )


@router.put(
    "/{workspace_id}/campaigns/{campaign_id}/members",
    response_model=CampaignMemberSummaryResponse,
)
async def upsert_campaign_member(
    workspace_id: UUID,
    campaign_id: UUID,
    payload: CampaignMemberUpsertRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> CampaignMemberSummaryResponse:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
    )
    try:
        link = await campaign_service.add_campaign_member(
            session,
            workspace_id,
            campaign_id,
            payload.workspace_membership_id,
            participation_status=payload.participation_status,
        )
    except CampaignRelationshipError as exc:
        _service_error(exc)
    links = await campaign_service.list_campaign_members(
        session,
        workspace_id,
        campaign_id,
    )
    for loaded in links:
        if loaded.workspace_membership_id == link.workspace_membership_id:
            return _member_response(loaded)
    raise _not_found()


@router.delete(
    "/{workspace_id}/campaigns/{campaign_id}/members/{workspace_membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_campaign_member(
    workspace_id: UUID,
    campaign_id: UUID,
    workspace_membership_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> Response:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
    )
    try:
        removed = await campaign_service.remove_campaign_member(
            session,
            workspace_id,
            campaign_id,
            workspace_membership_id,
        )
    except CampaignNotFoundError as exc:
        _service_error(exc)
    if not removed:
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{workspace_id}/campaigns/{campaign_id}/artists",
    response_model=CampaignArtistsListResponse,
)
async def list_campaign_artists(
    workspace_id: UUID,
    campaign_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> CampaignArtistsListResponse:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
    )
    try:
        links = await campaign_service.list_campaign_artists(
            session,
            workspace_id,
            campaign_id,
        )
    except CampaignNotFoundError as exc:
        _service_error(exc)
    return CampaignArtistsListResponse(
        artists=[_artist_link_response(link) for link in links]
    )


@router.put(
    "/{workspace_id}/campaigns/{campaign_id}/artists",
    response_model=CampaignArtistRelationshipResponse,
)
async def upsert_campaign_artist(
    workspace_id: UUID,
    campaign_id: UUID,
    payload: CampaignArtistUpsertRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> CampaignArtistRelationshipResponse:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
    )
    try:
        link = await campaign_service.associate_artist(
            session,
            workspace_id,
            campaign_id,
            payload.artist_id,
            relationship_kind=payload.relationship_kind,
            sort_order=payload.sort_order,
        )
    except CampaignRelationshipError as exc:
        _service_error(exc)
    links = await campaign_service.list_campaign_artists(
        session,
        workspace_id,
        campaign_id,
    )
    for loaded in links:
        if loaded.artist_id == link.artist_id:
            return _artist_link_response(loaded)
    raise _not_found()


@router.delete(
    "/{workspace_id}/campaigns/{campaign_id}/artists/{artist_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_campaign_artist(
    workspace_id: UUID,
    campaign_id: UUID,
    artist_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> Response:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
    )
    try:
        removed = await campaign_service.remove_artist_association(
            session,
            workspace_id,
            campaign_id,
            artist_id,
        )
    except CampaignNotFoundError as exc:
        _service_error(exc)
    if not removed:
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{workspace_id}/campaigns/{campaign_id}/releases",
    response_model=CampaignReleasesListResponse,
)
async def list_campaign_releases(
    workspace_id: UUID,
    campaign_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> CampaignReleasesListResponse:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_view,
    )
    try:
        links = await campaign_service.list_campaign_releases(
            session,
            workspace_id,
            campaign_id,
        )
    except CampaignNotFoundError as exc:
        _service_error(exc)
    return CampaignReleasesListResponse(
        releases=[_release_link_response(link) for link in links]
    )


@router.put(
    "/{workspace_id}/campaigns/{campaign_id}/releases",
    response_model=CampaignReleaseRelationshipResponse,
)
async def upsert_campaign_release(
    workspace_id: UUID,
    campaign_id: UUID,
    payload: CampaignReleaseUpsertRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> CampaignReleaseRelationshipResponse:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
    )
    try:
        link = await campaign_service.associate_release(
            session,
            workspace_id,
            campaign_id,
            payload.release_id,
            relationship_kind=payload.relationship_kind,
        )
    except CampaignRelationshipError as exc:
        _service_error(exc)
    links = await campaign_service.list_campaign_releases(
        session,
        workspace_id,
        campaign_id,
    )
    for loaded in links:
        if loaded.release_id == link.release_id:
            return _release_link_response(loaded)
    raise _not_found()


@router.delete(
    "/{workspace_id}/campaigns/{campaign_id}/releases/{release_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_campaign_release(
    workspace_id: UUID,
    campaign_id: UUID,
    release_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> Response:
    await _require_campaign_capability(
        session,
        context=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_campaign_edit,
    )
    try:
        removed = await campaign_service.remove_release_association(
            session,
            workspace_id,
            campaign_id,
            release_id,
        )
    except CampaignNotFoundError as exc:
        _service_error(exc)
    if not removed:
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
