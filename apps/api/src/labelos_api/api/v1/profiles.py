from typing import Annotated, Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from labelos_database.models import (
    ArtistProfile,
    Department,
    MembershipDepartmentAccess,
    MembershipProfessionalRole,
    OrganizationMembership,
    ProfessionalRole,
    ProfileAttribute,
    ProfileLink,
    ProfilePreference,
    Role,
    RoleCapability,
    UniversalProfile,
    WorkspaceMembership,
    WorkspaceMembershipRole,
)
from labelos_database.workspace_memberships import get_or_create_profile_for_user
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_api.auth import (
    CurrentUserContext,
    SessionDep,
    get_current_user_context,
)
from labelos_api.profile_completion import evaluate_profile_completion
from labelos_api.realtime import RealtimeEventType, RealtimePublisher

router = APIRouter(tags=["profiles"])

ProfileVisibility = Literal["owner", "shared"]
SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,118}[a-z0-9])?$"


class ProfileLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_type: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2048)
    label: str | None = Field(default=None, max_length=120)
    username: str | None = Field(default=None, max_length=120)
    external_id: str | None = Field(default=None, max_length=255)
    status: str = Field(default="active", min_length=1, max_length=60)
    is_primary: bool = False
    sort_order: int = Field(default=0, ge=0, le=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("link_type", "status")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value is required")
        return normalized

    @field_validator("label", "username", "external_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute HTTP(S) URL")
        return normalized


class ProfileAttributeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute_type: str = Field(min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=120)
    value: str = Field(min_length=1, max_length=500)
    source: str = Field(default="user", min_length=1, max_length=80)
    is_primary: bool = False
    sort_order: int = Field(default=0, ge=0, le=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("attribute_type", "value", "source")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value is required")
        return normalized

    @field_validator("label")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProfilePreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: str | None = Field(default=None, max_length=35)
    timezone: str | None = Field(default=None, max_length=120)
    default_workspace_id: UUID | None = None
    email_notifications_enabled: bool | None = None
    push_notifications_enabled: bool | None = None
    sms_notifications_enabled: bool | None = None
    marketing_notifications_enabled: bool | None = None
    interface_theme: str | None = Field(default=None, max_length=60)
    interface_density: str | None = Field(default=None, max_length=60)
    notification_preferences: dict[str, Any] | None = None
    interface_preferences: dict[str, Any] | None = None
    integration_preferences: dict[str, Any] | None = None

    @field_validator("locale", "timezone", "interface_theme", "interface_density")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=SLUG_PATTERN,
    )
    display_name: str | None = Field(default=None, max_length=200)
    headline: str | None = Field(default=None, max_length=240)
    biography: str | None = Field(default=None, max_length=4000)
    avatar_url: str | None = Field(default=None, max_length=2048)
    location: str | None = Field(default=None, max_length=240)
    timezone: str | None = Field(default=None, max_length=120)
    onboarding_status: str | None = Field(default=None, max_length=60)
    links: list[ProfileLinkRequest] | None = Field(default=None, max_length=50)
    attributes: list[ProfileAttributeRequest] | None = Field(
        default=None,
        max_length=100,
    )
    preferences: ProfilePreferencesRequest | None = None

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name is required")
        return normalized

    @field_validator("headline", "biography", "location", "timezone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("avatar_url must be an absolute HTTP(S) URL")
        return normalized

    @field_validator("onboarding_status")
    @classmethod
    def validate_onboarding_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized not in {"not_started", "in_progress", "complete"}:
            raise ValueError(
                "onboarding_status must be not_started, in_progress, or complete"
            )
        return normalized

    @model_validator(mode="after")
    def require_update(self) -> "ProfileUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one profile field is required")
        return self


class ProfileLinkResponse(BaseModel):
    id: UUID
    link_type: str
    label: str | None
    url: str
    username: str | None
    external_id: str | None
    status: str
    is_primary: bool
    sort_order: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProfileAttributeResponse(BaseModel):
    id: UUID
    attribute_type: str
    label: str | None
    value: str
    source: str
    is_primary: bool
    sort_order: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProfilePreferencesResponse(BaseModel):
    locale: str | None = None
    timezone: str | None = None
    default_workspace_id: UUID | None = None
    email_notifications_enabled: bool = True
    push_notifications_enabled: bool = True
    sms_notifications_enabled: bool = False
    marketing_notifications_enabled: bool = False
    interface_theme: str | None = None
    interface_density: str | None = None
    notification_preferences: dict[str, Any] = Field(default_factory=dict)
    interface_preferences: dict[str, Any] = Field(default_factory=dict)
    integration_preferences: dict[str, Any] = Field(default_factory=dict)


class ProfileCompletionResponse(BaseModel):
    ruleset: str
    is_complete: bool
    percent: int
    completed_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    guidance: str | None = None
    is_blocking: bool = False


class ProfileResponse(BaseModel):
    id: UUID
    user_id: UUID | None
    slug: str | None
    first_name: str | None
    last_name: str | None
    display_name: str | None
    headline: str | None
    biography: str | None
    avatar_url: str | None
    location: str | None
    timezone: str | None
    primary_email: str | None
    profile_status: str | None
    onboarding_status: str | None
    links: list[ProfileLinkResponse] = Field(default_factory=list)
    attributes: list[ProfileAttributeResponse] = Field(default_factory=list)
    preferences: ProfilePreferencesResponse
    profile_completion: ProfileCompletionResponse | None


class WorkspaceProfileMembershipResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    profile: ProfileResponse
    status: str
    joined_at: str | None
    role: str | None
    professional_roles: list[str] = Field(default_factory=list)
    department_access: list[str] = Field(default_factory=list)
    workspace_roles: list[str] = Field(default_factory=list)
    capability_permissions: list[str] = Field(default_factory=list)


class WorkspaceProfilesListResponse(BaseModel):
    profiles: list[WorkspaceProfileMembershipResponse]
    limit: int
    offset: int
    total: int


class WorkspacePeopleDirectoryEntry(BaseModel):
    id: UUID
    workspace_id: UUID
    profile_id: UUID
    avatar_url: str | None
    display_name: str | None
    headline: str | None
    roles: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    profile_modules: list[str] = Field(default_factory=list)
    artist_profile_id: UUID | None = None
    membership_status: str


class WorkspacePeopleDirectoryResponse(BaseModel):
    people: list[WorkspacePeopleDirectoryEntry]
    limit: int
    offset: int
    total: int
    query: str | None = None


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


async def _require_workspace_membership(
    session: AsyncSession,
    context: CurrentUserContext,
    workspace_id: UUID,
) -> None:
    context_has_active_membership = False
    for membership in context.memberships:
        if membership.workspace_id == workspace_id and membership.status == "active":
            context_has_active_membership = True
            break
    if not context_has_active_membership:
        raise _not_found()
    active_membership_id = await session.scalar(
        select(WorkspaceMembership.id)
        .join(WorkspaceMembership.profile)
        .where(UniversalProfile.user_id == context.user.id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.status == "active")
    )
    if active_membership_id is None:
        raise _not_found()


def _profile_options():
    return (
        selectinload(UniversalProfile.links),
        selectinload(UniversalProfile.attributes),
        selectinload(UniversalProfile.preference),
        selectinload(UniversalProfile.artist_profiles).selectinload(
            ArtistProfile.artist
        ),
    )


async def _load_profile(
    session: AsyncSession,
    profile_id: UUID,
) -> UniversalProfile | None:
    return await session.scalar(
        select(UniversalProfile)
        .options(*_profile_options())
        .execution_options(populate_existing=True)
        .where(UniversalProfile.id == profile_id)
    )


async def _can_read_profile(
    session: AsyncSession,
    *,
    context: CurrentUserContext,
    profile: UniversalProfile,
) -> bool:
    if profile.user_id == context.user.id:
        return True

    workspace_ids = [
        membership.workspace_id
        for membership in context.memberships
        if membership.status == "active"
    ]
    if not workspace_ids:
        return False

    active_actor_workspaces = (
        select(WorkspaceMembership.workspace_id)
        .join(WorkspaceMembership.profile)
        .where(UniversalProfile.user_id == context.user.id)
        .where(WorkspaceMembership.status == "active")
        .where(WorkspaceMembership.workspace_id.in_(workspace_ids))
    )
    shared_membership_id = await session.scalar(
        select(WorkspaceMembership.id)
        .where(WorkspaceMembership.profile_id == profile.id)
        .where(WorkspaceMembership.workspace_id.in_(active_actor_workspaces))
        .where(WorkspaceMembership.status == "active")
    )
    return shared_membership_id is not None


def _preferences_response(
    preference: ProfilePreference | None,
) -> ProfilePreferencesResponse:
    if preference is None:
        return ProfilePreferencesResponse()
    return ProfilePreferencesResponse(
        locale=preference.locale,
        timezone=preference.timezone,
        default_workspace_id=preference.default_workspace_id,
        email_notifications_enabled=preference.email_notifications_enabled,
        push_notifications_enabled=preference.push_notifications_enabled,
        sms_notifications_enabled=preference.sms_notifications_enabled,
        marketing_notifications_enabled=preference.marketing_notifications_enabled,
        interface_theme=preference.interface_theme,
        interface_density=preference.interface_density,
        notification_preferences=dict(preference.notification_preferences),
        interface_preferences=dict(preference.interface_preferences),
        integration_preferences=dict(preference.integration_preferences),
    )


def _profile_completion_response(
    profile: UniversalProfile,
    roles: list[str] | tuple[str, ...] = (),
) -> ProfileCompletionResponse:
    completion = evaluate_profile_completion(profile, roles)
    return ProfileCompletionResponse(
        ruleset=completion.ruleset,
        is_complete=completion.is_complete,
        percent=completion.percent,
        completed_fields=list(completion.completed_fields),
        missing_fields=list(completion.missing_fields),
        guidance=completion.guidance,
        is_blocking=completion.is_blocking,
    )


def _profile_response(
    profile: UniversalProfile,
    roles: list[str] | tuple[str, ...] = (),
    *,
    visibility: ProfileVisibility = "shared",
    include_private_preferences: bool = False,
) -> ProfileResponse:
    is_owner_visible = visibility == "owner"
    return ProfileResponse(
        id=profile.id,
        user_id=profile.user_id if is_owner_visible else None,
        slug=profile.slug,
        first_name=profile.first_name if is_owner_visible else None,
        last_name=profile.last_name if is_owner_visible else None,
        display_name=profile.display_name,
        headline=profile.headline,
        biography=profile.biography if is_owner_visible else None,
        avatar_url=profile.avatar_url,
        location=profile.location,
        timezone=profile.timezone if is_owner_visible else None,
        primary_email=profile.primary_email if is_owner_visible else None,
        profile_status=profile.profile_status if is_owner_visible else None,
        onboarding_status=profile.onboarding_status if is_owner_visible else None,
        links=(
            [
                ProfileLinkResponse(
                    id=link.id,
                    link_type=link.link_type,
                    label=link.label,
                    url=link.url,
                    username=link.username,
                    external_id=link.external_id,
                    status=link.status,
                    is_primary=link.is_primary,
                    sort_order=link.sort_order,
                    metadata=dict(link.metadata_json),
                )
                for link in profile.links
            ]
            if is_owner_visible
            else []
        ),
        attributes=(
            [
                ProfileAttributeResponse(
                    id=attribute.id,
                    attribute_type=attribute.attribute_type,
                    label=attribute.label,
                    value=attribute.value,
                    source=attribute.source,
                    is_primary=attribute.is_primary,
                    sort_order=attribute.sort_order,
                    metadata=dict(attribute.metadata_json),
                )
                for attribute in profile.attributes
            ]
            if is_owner_visible
            else []
        ),
        preferences=_preferences_response(
            profile.preference if include_private_preferences else None
        ),
        profile_completion=(
            _profile_completion_response(profile, roles) if is_owner_visible else None
        ),
    )


def _workspace_profile_response(
    membership: WorkspaceMembership,
    *,
    profile_visibility: ProfileVisibility = "shared",
) -> WorkspaceProfileMembershipResponse:
    organization_membership = membership.organization_membership
    return WorkspaceProfileMembershipResponse(
        id=membership.id,
        workspace_id=membership.workspace_id,
        profile=_profile_response(
            membership.profile,
            [
                *membership.professional_roles,
                *membership.role_keys,
                *(
                    [organization_membership.workspace_permission.value]
                    if organization_membership is not None
                    else []
                ),
            ],
            visibility=profile_visibility,
            include_private_preferences=False,
        ),
        status=membership.status,
        joined_at=membership.joined_at.isoformat() if membership.joined_at else None,
        role=(
            organization_membership.workspace_permission.value
            if organization_membership is not None
            and organization_membership.workspace_permission is not None
            else None
        ),
        professional_roles=list(membership.professional_roles),
        department_access=list(membership.department_access),
        workspace_roles=list(membership.role_keys),
        capability_permissions=list(membership.capability_keys),
    )


def _profile_module_keys(profile: UniversalProfile) -> list[str]:
    modules = [
        module_key
        for module_key, module_records in profile.profile_modules.items()
        if module_records
    ]
    return modules or ["universal"]


def _directory_entry(
    membership: WorkspaceMembership,
) -> WorkspacePeopleDirectoryEntry:
    organization_membership = membership.organization_membership
    artist_profile = next(
        (
            artist_profile
            for artist_profile in membership.profile.artist_profiles
            if artist_profile.artist.organization_id == membership.workspace_id
        ),
        None,
    )
    roles = [
        *membership.professional_roles,
        *membership.role_keys,
        *(
            [organization_membership.workspace_permission.value]
            if organization_membership is not None
            and organization_membership.workspace_permission is not None
            else []
        ),
    ]
    return WorkspacePeopleDirectoryEntry(
        id=membership.id,
        workspace_id=membership.workspace_id,
        profile_id=membership.profile_id,
        avatar_url=membership.profile.avatar_url,
        display_name=membership.profile.display_name,
        headline=membership.profile.headline,
        roles=list(dict.fromkeys(roles)),
        departments=list(membership.department_access),
        profile_modules=_profile_module_keys(membership.profile),
        artist_profile_id=artist_profile.id if artist_profile is not None else None,
        membership_status=membership.status,
    )


def _directory_search_filter(search: str):
    pattern = f"%{search}%"
    professional_role_match = exists(
        select(1)
        .select_from(MembershipProfessionalRole)
        .join(ProfessionalRole)
        .where(
            MembershipProfessionalRole.membership_id
            == WorkspaceMembership.organization_membership_id
        )
        .where(MembershipProfessionalRole.status == "active")
        .where(
            or_(
                ProfessionalRole.display_name.ilike(pattern),
                ProfessionalRole.slug.ilike(pattern),
            )
        )
    )
    department_match = exists(
        select(1)
        .select_from(MembershipDepartmentAccess)
        .join(Department)
        .where(
            MembershipDepartmentAccess.membership_id
            == WorkspaceMembership.organization_membership_id
        )
        .where(
            or_(
                Department.display_name.ilike(pattern),
                Department.slug.ilike(pattern),
            )
        )
    )
    workspace_role_match = exists(
        select(1)
        .select_from(WorkspaceMembershipRole)
        .join(Role)
        .where(WorkspaceMembershipRole.membership_id == WorkspaceMembership.id)
        .where(or_(Role.display_name.ilike(pattern), Role.key.ilike(pattern)))
    )
    return or_(
        UniversalProfile.display_name.ilike(pattern),
        professional_role_match,
        workspace_role_match,
        department_match,
    )


async def _replace_links(
    session: AsyncSession,
    profile_id: UUID,
    links: list[ProfileLinkRequest],
) -> None:
    await session.execute(
        delete(ProfileLink).where(ProfileLink.profile_id == profile_id)
    )
    for link in links:
        session.add(
            ProfileLink(
                profile_id=profile_id,
                link_type=link.link_type,
                label=link.label,
                url=link.url,
                username=link.username,
                external_id=link.external_id,
                status=link.status,
                is_primary=link.is_primary,
                sort_order=link.sort_order,
                metadata_json=link.metadata,
            )
        )


async def _replace_attributes(
    session: AsyncSession,
    profile_id: UUID,
    attributes: list[ProfileAttributeRequest],
) -> None:
    await session.execute(
        delete(ProfileAttribute).where(ProfileAttribute.profile_id == profile_id)
    )
    for attribute in attributes:
        session.add(
            ProfileAttribute(
                profile_id=profile_id,
                attribute_type=attribute.attribute_type,
                label=attribute.label,
                value=attribute.value,
                source=attribute.source,
                is_primary=attribute.is_primary,
                sort_order=attribute.sort_order,
                metadata_json=attribute.metadata,
            )
        )


def _apply_preference_changes(
    profile: UniversalProfile,
    preferences: ProfilePreferencesRequest,
) -> None:
    if profile.preference is None:
        profile.preference = ProfilePreference(profile_id=profile.id)
    changes = preferences.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(profile.preference, key, value)


async def _current_profile(
    session: AsyncSession,
    context: CurrentUserContext,
) -> UniversalProfile:
    existing_profile_id = await session.scalar(
        select(UniversalProfile.id).where(UniversalProfile.user_id == context.user.id)
    )
    profile = await get_or_create_profile_for_user(session, context.user)
    await session.flush()
    if existing_profile_id is None:
        await session.commit()
    loaded_profile = await _load_profile(session, profile.id)
    if loaded_profile is None:
        raise _not_found()
    return loaded_profile


def _active_workspace_id(context: CurrentUserContext) -> UUID | None:
    active_membership = context.active_membership
    if active_membership is None:
        return None
    return active_membership.workspace_id


async def _publish_profile_activity(
    session: AsyncSession,
    *,
    context: CurrentUserContext,
    event_type: RealtimeEventType,
    profile: UniversalProfile,
    metadata: dict[str, Any] | None = None,
) -> None:
    workspace_id = _active_workspace_id(context)
    if workspace_id is None:
        return

    await RealtimePublisher(session).publish(
        organization_id=workspace_id,
        event_type=event_type,
        actor=context.user,
        entity_type="profile",
        entity_id=profile.id,
        payload={
            "profileId": str(profile.id),
            "workspaceId": str(workspace_id),
            **(metadata or {}),
        },
    )


@router.get("/profiles/me", response_model=ProfileResponse)
async def get_my_profile(
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> ProfileResponse:
    profile = await _current_profile(session, context)
    active_membership = context.active_membership
    return _profile_response(
        profile,
        [
            *(active_membership.professional_roles if active_membership else ()),
            *(active_membership.role_capabilities if active_membership else ()),
            *(
                [active_membership.workspace_permission.value]
                if active_membership is not None
                else []
            ),
        ],
        visibility="owner",
        include_private_preferences=True,
    )


@router.patch("/profiles/me", response_model=ProfileResponse)
async def update_my_profile(
    payload: ProfileUpdateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> ProfileResponse:
    existing_profile_id = await session.scalar(
        select(UniversalProfile.id).where(UniversalProfile.user_id == context.user.id)
    )
    profile = await _current_profile(session, context)
    scalar_changes = payload.model_dump(
        include={
            "display_name",
            "slug",
            "headline",
            "biography",
            "avatar_url",
            "location",
            "timezone",
            "onboarding_status",
        },
        exclude_unset=True,
    )
    for key, value in scalar_changes.items():
        setattr(profile, key, value)
    if payload.links is not None:
        await _replace_links(session, profile.id, payload.links)
    if payload.attributes is not None:
        await _replace_attributes(session, profile.id, payload.attributes)
    if payload.preferences is not None:
        _apply_preference_changes(profile, payload.preferences)

    try:
        if existing_profile_id is None:
            await _publish_profile_activity(
                session,
                context=context,
                event_type=RealtimeEventType.profile_created,
                profile=profile,
            )
        changed_fields = sorted(payload.model_fields_set)
        await _publish_profile_activity(
            session,
            context=context,
            event_type=RealtimeEventType.profile_updated,
            profile=profile,
            metadata={"changedFields": changed_fields},
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict("Profile update conflicts with an existing record") from exc

    updated_profile = await _load_profile(session, profile.id)
    if updated_profile is None:
        raise _not_found()
    active_membership = context.active_membership
    return _profile_response(
        updated_profile,
        [
            *(active_membership.professional_roles if active_membership else ()),
            *(active_membership.role_capabilities if active_membership else ()),
            *(
                [active_membership.workspace_permission.value]
                if active_membership is not None
                else []
            ),
        ],
        visibility="owner",
        include_private_preferences=True,
    )


@router.get("/profiles/{profile_id}", response_model=ProfileResponse)
async def get_profile(
    profile_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> ProfileResponse:
    profile = await _load_profile(session, profile_id)
    if profile is None:
        raise _not_found()
    if not await _can_read_profile(session, context=context, profile=profile):
        raise _not_found()
    is_owner = profile.user_id == context.user.id
    return _profile_response(
        profile,
        visibility="owner" if is_owner else "shared",
        include_private_preferences=is_owner,
    )


@router.get(
    "/workspaces/{workspace_id}/profiles",
    response_model=WorkspaceProfilesListResponse,
)
async def list_workspace_profiles(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkspaceProfilesListResponse:
    await _require_workspace_membership(session, context, workspace_id)
    total = await session.scalar(
        select(func.count())
        .select_from(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.status == "active")
    )
    memberships = await session.scalars(
        select(WorkspaceMembership)
        .options(
            selectinload(WorkspaceMembership.profile).selectinload(
                UniversalProfile.links
            ),
            selectinload(WorkspaceMembership.profile).selectinload(
                UniversalProfile.attributes
            ),
            selectinload(WorkspaceMembership.profile).selectinload(
                UniversalProfile.preference
            ),
            selectinload(WorkspaceMembership.profile)
            .selectinload(UniversalProfile.artist_profiles)
            .selectinload(ArtistProfile.artist),
            selectinload(WorkspaceMembership.organization_membership)
            .selectinload(OrganizationMembership.professional_role_links)
            .selectinload(MembershipProfessionalRole.professional_role),
            selectinload(WorkspaceMembership.organization_membership)
            .selectinload(OrganizationMembership.department_access_grants)
            .selectinload(MembershipDepartmentAccess.department),
            selectinload(WorkspaceMembership.role_assignments).selectinload(
                WorkspaceMembershipRole.role
            ),
            selectinload(WorkspaceMembership.role_assignments)
            .selectinload(WorkspaceMembershipRole.role)
            .selectinload(Role.capability_links)
            .selectinload(RoleCapability.capability),
        )
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.status == "active")
        .order_by(WorkspaceMembership.joined_at.asc(), WorkspaceMembership.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return WorkspaceProfilesListResponse(
        profiles=[
            _workspace_profile_response(
                membership,
                profile_visibility=(
                    "owner"
                    if membership.profile.user_id == context.user.id
                    else "shared"
                ),
            )
            for membership in memberships.all()
        ],
        limit=limit,
        offset=offset,
        total=total or 0,
    )


@router.get(
    "/workspaces/{workspace_id}/people",
    response_model=WorkspacePeopleDirectoryResponse,
)
async def list_workspace_people_directory(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    query: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkspacePeopleDirectoryResponse:
    await _require_workspace_membership(session, context, workspace_id)
    normalized_query = query.strip() if query else None
    if normalized_query == "":
        normalized_query = None

    filters = [
        WorkspaceMembership.workspace_id == workspace_id,
        WorkspaceMembership.status == "active",
    ]
    if normalized_query is not None:
        filters.append(_directory_search_filter(normalized_query))

    total = await session.scalar(
        select(func.count())
        .select_from(WorkspaceMembership)
        .join(WorkspaceMembership.profile)
        .where(*filters)
    )
    memberships = await session.scalars(
        select(WorkspaceMembership)
        .join(WorkspaceMembership.profile)
        .options(
            selectinload(WorkspaceMembership.profile)
            .selectinload(UniversalProfile.artist_profiles)
            .selectinload(ArtistProfile.artist),
            selectinload(WorkspaceMembership.organization_membership)
            .selectinload(OrganizationMembership.professional_role_links)
            .selectinload(MembershipProfessionalRole.professional_role),
            selectinload(WorkspaceMembership.organization_membership)
            .selectinload(OrganizationMembership.department_access_grants)
            .selectinload(MembershipDepartmentAccess.department),
            selectinload(WorkspaceMembership.role_assignments).selectinload(
                WorkspaceMembershipRole.role
            ),
        )
        .where(*filters)
        .order_by(
            func.lower(UniversalProfile.display_name).asc(),
            WorkspaceMembership.joined_at.asc(),
            WorkspaceMembership.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return WorkspacePeopleDirectoryResponse(
        people=[_directory_entry(membership) for membership in memberships.all()],
        limit=limit,
        offset=offset,
        total=total or 0,
        query=normalized_query,
    )


@router.get(
    "/workspaces/{workspace_id}/profiles/{profile_id}",
    response_model=WorkspaceProfileMembershipResponse,
)
async def get_workspace_profile(
    workspace_id: UUID,
    profile_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> WorkspaceProfileMembershipResponse:
    await _require_workspace_membership(session, context, workspace_id)
    membership = await session.scalar(
        select(WorkspaceMembership)
        .options(
            selectinload(WorkspaceMembership.profile).selectinload(
                UniversalProfile.links
            ),
            selectinload(WorkspaceMembership.profile).selectinload(
                UniversalProfile.attributes
            ),
            selectinload(WorkspaceMembership.profile).selectinload(
                UniversalProfile.preference
            ),
            selectinload(WorkspaceMembership.profile).selectinload(
                UniversalProfile.artist_profiles
            ),
            selectinload(WorkspaceMembership.organization_membership)
            .selectinload(OrganizationMembership.professional_role_links)
            .selectinload(MembershipProfessionalRole.professional_role),
            selectinload(WorkspaceMembership.organization_membership)
            .selectinload(OrganizationMembership.department_access_grants)
            .selectinload(MembershipDepartmentAccess.department),
            selectinload(WorkspaceMembership.role_assignments).selectinload(
                WorkspaceMembershipRole.role
            ),
            selectinload(WorkspaceMembership.role_assignments)
            .selectinload(WorkspaceMembershipRole.role)
            .selectinload(Role.capability_links)
            .selectinload(RoleCapability.capability),
        )
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.profile_id == profile_id)
        .where(WorkspaceMembership.status == "active")
    )
    if membership is None:
        raise _not_found()
    return _workspace_profile_response(
        membership,
        profile_visibility=(
            "owner" if membership.profile.user_id == context.user.id else "shared"
        ),
    )
