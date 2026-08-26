from labelos_database.models import ArtistProfile, ProfileLink, UniversalProfile

from labelos_api.profile_completion import (
    CompletionFieldRule,
    CompletionRuleSet,
    completion_ruleset_for_roles,
    evaluate_profile_completion,
)


def test_professional_profile_completion_reports_missing_fields() -> None:
    profile = UniversalProfile(
        display_name="Mira Stone",
        headline="",
        avatar_url=None,
    )

    completion = evaluate_profile_completion(profile, roles=("analytics",))

    assert completion.ruleset == "professional"
    assert completion.percent == 33
    assert completion.is_complete is False
    assert completion.completed_fields == ("Display name",)
    assert completion.missing_fields == ("Professional headline", "Profile image")
    assert completion.guidance == "Add your professional information"


def test_manager_completion_accepts_active_contact_or_website_links() -> None:
    profile = UniversalProfile(
        display_name="Avery Manager",
        headline="Artist manager",
        links=[
            ProfileLink(
                link_type="website",
                url="https://example.com/avery",
                status="inactive",
            ),
            ProfileLink(
                link_type="linkedin",
                url="https://linkedin.com/in/avery",
                status="active",
            ),
        ],
    )

    completion = evaluate_profile_completion(profile, roles=("Artist Manager",))

    assert completion.ruleset == "manager"
    assert completion.is_complete is True
    assert completion.percent == 100
    assert completion.missing_fields == ()
    assert completion.guidance is None


def test_artist_completion_uses_artist_module_image_and_dsp_links() -> None:
    profile = UniversalProfile(
        display_name=None,
        biography="Release-ready artist biography.",
        artist_profiles=[
            ArtistProfile(
                stage_name="Night Chorus",
                imagery={"press": "https://cdn.example.com/night-chorus.jpg"},
                dsp_links={"spotify": "https://open.spotify.com/artist/night"},
            )
        ],
    )

    completion = evaluate_profile_completion(profile, roles=("recording artist",))

    assert completion.ruleset == "artist"
    assert completion.is_complete is True
    assert completion.completed_fields == (
        "Artist name",
        "Artist image",
        "Biography",
        "DSP links",
    )


def test_artist_completion_ignores_blank_artist_module_values() -> None:
    profile = UniversalProfile(
        display_name="",
        biography="",
        avatar_url="",
        artist_profiles=[
            ArtistProfile(
                stage_name=" ",
                imagery={"press": ""},
                dsp_links={"spotify": " "},
            )
        ],
    )

    completion = evaluate_profile_completion(profile, roles=("performer",))

    assert completion.ruleset == "artist"
    assert completion.percent == 0
    assert completion.completed_fields == ()
    assert completion.missing_fields == (
        "Artist name",
        "Artist image",
        "Biography",
        "DSP links",
    )


def test_completion_ruleset_falls_back_for_blank_roles() -> None:
    rule_set = completion_ruleset_for_roles((" ", "unknown-role"))

    assert rule_set.key == "professional"


def test_empty_completion_ruleset_is_complete() -> None:
    profile = UniversalProfile(display_name=None)
    empty_ruleset = CompletionRuleSet(
        key="empty",
        guidance="No profile fields required",
        fields=(),
        role_aliases=("empty",),
    )

    completion = evaluate_profile_completion(
        profile,
        roles=("empty",),
        rule_sets=(empty_ruleset,),
    )

    assert completion.ruleset == "empty"
    assert completion.is_complete is True
    assert completion.percent == 100
    assert completion.completed_fields == ()
    assert completion.missing_fields == ()
    assert completion.guidance is None


def test_custom_completion_ruleset_reports_partial_completion() -> None:
    profile = UniversalProfile(display_name="Custom User")
    custom_ruleset = CompletionRuleSet(
        key="custom",
        guidance="Fill custom fields",
        fields=(
            CompletionFieldRule(
                key="display_name",
                label="Display name",
                is_complete=lambda candidate: bool(candidate.display_name),
            ),
            CompletionFieldRule(
                key="headline",
                label="Headline",
                is_complete=lambda candidate: bool(candidate.headline),
            ),
        ),
        role_aliases=("custom",),
    )

    completion = evaluate_profile_completion(
        profile,
        roles=("custom",),
        rule_sets=(custom_ruleset,),
    )

    assert completion.percent == 50
    assert completion.completed_fields == ("Display name",)
    assert completion.missing_fields == ("Headline",)
    assert completion.guidance == "Fill custom fields"
