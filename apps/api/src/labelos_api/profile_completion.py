from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from labelos_database.models import ArtistProfile, ProfileLink, UniversalProfile


@dataclass(frozen=True)
class CompletionFieldRule:
    key: str
    label: str
    is_complete: Callable[[UniversalProfile], bool]


@dataclass(frozen=True)
class CompletionRuleSet:
    key: str
    guidance: str
    fields: tuple[CompletionFieldRule, ...]
    role_aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileCompletion:
    ruleset: str
    is_complete: bool
    percent: int
    completed_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    guidance: str | None
    is_blocking: bool = False


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _has_link(profile: UniversalProfile, link_types: set[str] | None = None) -> bool:
    for link in profile.links:
        if not _active_link(link):
            continue
        if link_types is None or link.link_type in link_types:
            return True
    return False


def _active_link(link: ProfileLink) -> bool:
    return link.status == "active" and _has_text(link.url)


def _artist_profiles(profile: UniversalProfile) -> list[ArtistProfile]:
    return list(getattr(profile, "artist_profiles", []) or [])


def _has_artist_name(profile: UniversalProfile) -> bool:
    return _has_text(profile.display_name) or any(
        _has_text(artist_profile.stage_name)
        for artist_profile in _artist_profiles(profile)
    )


def _has_artist_image(profile: UniversalProfile) -> bool:
    if _has_text(profile.avatar_url):
        return True
    for artist_profile in _artist_profiles(profile):
        imagery = artist_profile.imagery or {}
        if any(
            _has_text(str(value)) for value in imagery.values() if value is not None
        ):
            return True
    return False


def _has_artist_dsp_link(profile: UniversalProfile) -> bool:
    dsp_link_types = {"spotify", "apple_music", "youtube", "soundcloud", "tidal"}
    if _has_link(profile, dsp_link_types):
        return True
    for artist_profile in _artist_profiles(profile):
        dsp_links = artist_profile.dsp_links or {}
        if any(
            _has_text(str(value)) for value in dsp_links.values() if value is not None
        ):
            return True
    return False


DEFAULT_RULESET = CompletionRuleSet(
    key="professional",
    guidance="Add your professional information",
    fields=(
        CompletionFieldRule(
            key="display_name",
            label="Display name",
            is_complete=lambda profile: _has_text(profile.display_name),
        ),
        CompletionFieldRule(
            key="headline",
            label="Professional headline",
            is_complete=lambda profile: _has_text(profile.headline),
        ),
        CompletionFieldRule(
            key="avatar",
            label="Profile image",
            is_complete=lambda profile: _has_text(profile.avatar_url),
        ),
    ),
)

PROFILE_COMPLETION_RULESETS: tuple[CompletionRuleSet, ...] = (
    CompletionRuleSet(
        key="artist",
        guidance="Complete your artist profile",
        role_aliases=("artist", "performer", "recording artist"),
        fields=(
            CompletionFieldRule(
                key="artist_name",
                label="Artist name",
                is_complete=_has_artist_name,
            ),
            CompletionFieldRule(
                key="image",
                label="Artist image",
                is_complete=_has_artist_image,
            ),
            CompletionFieldRule(
                key="biography",
                label="Biography",
                is_complete=lambda profile: _has_text(profile.biography),
            ),
            CompletionFieldRule(
                key="dsp_links",
                label="DSP links",
                is_complete=_has_artist_dsp_link,
            ),
        ),
    ),
    CompletionRuleSet(
        key="manager",
        guidance="Add your professional information",
        role_aliases=("manager", "management", "artist manager"),
        fields=(
            CompletionFieldRule(
                key="display_name",
                label="Display name",
                is_complete=lambda profile: _has_text(profile.display_name),
            ),
            CompletionFieldRule(
                key="headline",
                label="Professional headline",
                is_complete=lambda profile: _has_text(profile.headline),
            ),
            CompletionFieldRule(
                key="contact_or_website",
                label="Contact or website link",
                is_complete=lambda profile: _has_link(
                    profile,
                    {"website", "linkedin", "email", "instagram"},
                ),
            ),
        ),
    ),
    DEFAULT_RULESET,
)


def completion_ruleset_for_roles(
    roles: Iterable[str],
    *,
    rule_sets: tuple[CompletionRuleSet, ...] = PROFILE_COMPLETION_RULESETS,
) -> CompletionRuleSet:
    normalized_roles = {role.strip().lower() for role in roles if role.strip()}
    for rule_set in rule_sets:
        if normalized_roles.intersection(rule_set.role_aliases):
            return rule_set
    return DEFAULT_RULESET


def evaluate_profile_completion(
    profile: UniversalProfile,
    roles: Iterable[str] = (),
    *,
    rule_sets: tuple[CompletionRuleSet, ...] = PROFILE_COMPLETION_RULESETS,
) -> ProfileCompletion:
    rule_set = completion_ruleset_for_roles(roles, rule_sets=rule_sets)
    completed_fields = tuple(
        field.label for field in rule_set.fields if field.is_complete(profile)
    )
    missing_fields = tuple(
        field.label for field in rule_set.fields if not field.is_complete(profile)
    )
    percent = (
        round((len(completed_fields) / len(rule_set.fields)) * 100)
        if rule_set.fields
        else 100
    )
    is_complete = not missing_fields
    return ProfileCompletion(
        ruleset=rule_set.key,
        is_complete=is_complete,
        percent=percent,
        completed_fields=completed_fields,
        missing_fields=missing_fields,
        guidance=None if is_complete else rule_set.guidance,
    )
