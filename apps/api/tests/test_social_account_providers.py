import asyncio
import inspect

import pytest
from labelos_database.models import SocialAccountConnectionMethod

from labelos_api.social_accounts.providers import (
    AssistedSocialAccountConnectionProvider,
    SocialAccountConnectionProvider,
    SocialAccountHealth,
    SocialAccountIdentity,
    SocialAccountProviderError,
    SocialAccountProviderErrorCode,
    SocialAccountProviderKey,
    SocialAccountProviderRegistry,
    canonical_provider_key,
    default_social_account_provider_registry,
)


class FakeDirectInstagramProvider(SocialAccountConnectionProvider):
    provider = SocialAccountProviderKey.instagram
    connection_method = SocialAccountConnectionMethod.direct_api

    def default_capabilities(self) -> tuple[str, ...]:
        return ("account_analytics_read", "post_analytics_read")

    async def check_connection_health(
        self,
        *,
        credential_ref: str | None,
        token_expires_at=None,
        provider_metadata=None,
    ) -> SocialAccountHealth:
        return SocialAccountHealth(healthy=False, status="expired")


class FailingIdentityProvider(FakeDirectInstagramProvider):
    async def retrieve_account_identity(
        self,
        *,
        credential_ref: str | None,
        provider_metadata=None,
    ) -> SocialAccountIdentity:
        raise SocialAccountProviderError(
            SocialAccountProviderErrorCode.credential_expired,
            "Credential expired",
            provider=self.provider,
            connection_method=self.connection_method,
        )


def test_provider_registry_registers_and_resolves_by_provider_and_method() -> None:
    assisted = AssistedSocialAccountConnectionProvider(
        SocialAccountProviderKey.instagram
    )
    direct = FakeDirectInstagramProvider()
    registry = SocialAccountProviderRegistry([assisted, direct])

    assert registry.resolve("instagram", "assisted") is assisted
    assert registry.resolve("Instagram", "direct_api") is direct
    assert registry.supported_connection_methods("instagram") == (
        SocialAccountConnectionMethod.assisted,
        SocialAccountConnectionMethod.direct_api,
    )


def test_provider_registry_rejects_duplicate_registration() -> None:
    registry = SocialAccountProviderRegistry(
        [AssistedSocialAccountConnectionProvider(SocialAccountProviderKey.spotify)]
    )

    with pytest.raises(ValueError):
        registry.register(
            AssistedSocialAccountConnectionProvider(SocialAccountProviderKey.spotify)
        )


def test_default_registry_exposes_safe_provider_keys_without_direct_api_support() -> (
    None
):
    registry = default_social_account_provider_registry()

    for provider in SocialAccountProviderKey:
        adapter = registry.resolve(provider, SocialAccountConnectionMethod.assisted)
        assert adapter.provider == provider

        with pytest.raises(SocialAccountProviderError) as exc_info:
            registry.resolve(provider, SocialAccountConnectionMethod.direct_api)
        assert (
            exc_info.value.code
            == SocialAccountProviderErrorCode.unsupported_connection_method
        )


def test_registry_reports_unsupported_provider_and_method_separately() -> None:
    registry = SocialAccountProviderRegistry(
        [AssistedSocialAccountConnectionProvider(SocialAccountProviderKey.youtube)]
    )

    with pytest.raises(SocialAccountProviderError) as provider_exc:
        registry.resolve("threads", "assisted")
    assert (
        provider_exc.value.code == SocialAccountProviderErrorCode.unsupported_provider
    )

    with pytest.raises(SocialAccountProviderError) as method_exc:
        registry.resolve("youtube", "enterprise_partner")
    assert (
        method_exc.value.code
        == SocialAccountProviderErrorCode.unsupported_connection_method
    )


def test_provider_error_codes_are_normalized() -> None:
    provider = FailingIdentityProvider()

    async def run() -> None:
        with pytest.raises(SocialAccountProviderError) as exc_info:
            await provider.retrieve_account_identity(credential_ref="vault://expired")
        assert exc_info.value.code == SocialAccountProviderErrorCode.credential_expired
        assert exc_info.value.provider == "instagram"
        assert exc_info.value.connection_method == "direct_api"

    asyncio.run(run())


def test_capability_and_identity_normalization() -> None:
    adapter = AssistedSocialAccountConnectionProvider(SocialAccountProviderKey.x)

    assert canonical_provider_key("Twitter") == "x"
    assert adapter.normalize_capabilities(()) == ["manual_publish"]
    assert adapter.normalize_capabilities(
        ["manual_publish", " manual_publish "]
    ) == ["manual_publish"]
    with pytest.raises(SocialAccountProviderError):
        adapter.normalize_capabilities(["account_analytics_read"])

    result = adapter.validate_account_input(
        SocialAccountIdentity(
            provider="twitter",
            external_account_id=" ext-1 ",
            username=" @LabelOS ",
            display_name=" Label OS ",
            profile_url=" https://x.com/labelos ",
        ),
        provider_metadata={"source": "manual"},
    )
    assert result.identity == SocialAccountIdentity(
        provider="x",
        external_account_id="ext-1",
        username="labelos",
        display_name="Label OS",
        profile_url="https://x.com/labelos",
    )
    assert result.provider_metadata == {"source": "manual"}


def test_assisted_provider_rejects_unsafe_profile_urls() -> None:
    adapter = AssistedSocialAccountConnectionProvider(
        SocialAccountProviderKey.instagram
    )

    with pytest.raises(SocialAccountProviderError):
        adapter.validate_account_input(
            SocialAccountIdentity(
                provider="instagram",
                username="labelos",
                profile_url="javascript:alert(1)",
            )
        )

    with pytest.raises(SocialAccountProviderError):
        adapter.validate_account_input(
            SocialAccountIdentity(
                provider="instagram",
                username="labelos",
                profile_url="https://user:pass@example.com/labelos",
            )
        )


def test_assisted_provider_health_is_manual_action_required() -> None:
    adapter = AssistedSocialAccountConnectionProvider(SocialAccountProviderKey.tiktok)

    async def run() -> SocialAccountHealth:
        return await adapter.check_connection_health(credential_ref=None)

    health = asyncio.run(run())
    assert health.healthy is True
    assert health.status == "assisted_action_required"


def test_connection_provider_contract_has_no_fastapi_request_dependency() -> None:
    for method_name, method in inspect.getmembers(
        SocialAccountConnectionProvider,
        predicate=inspect.isfunction,
    ):
        if (
            method_name.startswith("__")
            or method_name not in SocialAccountConnectionProvider.__dict__
        ):
            continue
        signature = inspect.signature(method)
        for parameter in signature.parameters.values():
            if parameter.name == "self":
                continue
            assert parameter.annotation is not inspect.Signature.empty
            assert "fastapi" not in repr(parameter.annotation).lower()
        assert "fastapi" not in repr(signature.return_annotation).lower()
