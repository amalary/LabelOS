"""Explicit no-I/O adapter: Spotify's analysis policy blocks the A&R use case."""

from labelos_api.research.adapters.common import HTTPAdapter
from labelos_api.research.contracts import (
    AuthenticationRequirements,
    ProviderDescriptor,
)


class SpotifyAdapter(HTTPAdapter):
    license_url = "https://developer.spotify.com/policy"
    descriptor = ProviderDescriptor(
        key="spotify",
        display_name="Spotify",
        adapter_version="1.0.0",
        capabilities=frozenset(),
        resources=frozenset(),
        authentication=AuthenticationRequirements(
            method="oauth2", required_fields=("access_token",)
        ),
    )

    @property
    def blocked_reason(self) -> str:
        return "policy_prohibits_content_analysis"
