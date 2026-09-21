"""Explicit trusted host composition using the existing Social Accounts registry."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labelos_api.publishing.providers import ProviderRegistry
from labelos_api.publishing.youtube import YouTubePublishingAdapter
from labelos_api.social_accounts.providers import (
    SocialAccountProviderError,
    SocialAccountProviderRegistry,
    YouTubeDirectSocialAccountConnectionProvider,
)


def publishing_provider_registry(
    *,
    sessions: async_sessionmaker[AsyncSession],
    social_account_registry: SocialAccountProviderRegistry,
) -> ProviderRegistry:
    """Reuse the configured OAuth adapter and its exact credential-store instance.

    No settings/credential store is created here. The trusted delivery host passes
    this registry to execute; the core's omitted-registry behavior stays closed.
    """
    try:
        provider = social_account_registry.resolve("youtube", "direct_api")
    except SocialAccountProviderError:
        return ProviderRegistry()
    if not isinstance(provider, YouTubeDirectSocialAccountConnectionProvider):
        return ProviderRegistry()
    if provider.credential_store is None:
        return ProviderRegistry()
    return ProviderRegistry(
        {
            "youtube": YouTubePublishingAdapter(
                sessions=sessions, connection_provider=provider
            )
        }
    )
