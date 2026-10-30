"""Authorized, display-only requests using a pinned collection's provenance."""

from uuid import UUID

from labelos_database.models import (
    AnalyticsProvider,
    CollectionRun,
    DatasetDocumentation,
    DatasetVersion,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

from labelos_api.config import Settings
from labelos_api.research.adapters.common import RequestGate
from labelos_api.research.adapters.youtube import YouTubeAdapter
from labelos_api.research.contracts import CollectionContext, ProviderConfiguration
from labelos_api.research.providers import ProviderClient
from labelos_api.research.youtube_cache import CachedYouTubeClient
from labelos_api.research.youtube_quota import YouTubeQuota
from labelos_api.services.credential_store import (
    CredentialStoreUnavailableError,
    build_credential_store,
)
from labelos_api.services.governance_service import (
    GovernanceConflict,
    GovernanceService,
)
from labelos_api.services.scouting_service import authorize_scout


class ResearchNotConfigured(Exception):
    pass


class YouTubeResearchService(GovernanceService):
    async def client_for_run(self, run_id: UUID, settings: Settings):
        # Authorize before looking up either configuration or a secret. Callers
        # cannot provide provider IDs, credential references or arbitrary URLs.
        await authorize_scout(self.session, self.workspace_id, self.actor)
        run = await self._load(CollectionRun, run_id, lock=True)
        if run.status != "running":
            raise GovernanceConflict("YouTube research requires a running collection")
        source = await self._load(AnalyticsProvider, run.source_id)
        if source.key != "youtube":
            raise GovernanceConflict("Collection source must be YouTube")
        version = await self._load(DatasetVersion, run.version_id, lock=True)
        if version.state == "archived":
            raise GovernanceConflict("Archived versions cannot collect data")
        if not run.production and settings.requires_strict_startup_validation:
            raise GovernanceConflict(
                "Production environments require a production collection"
            )
        if run.production:
            await self._production_document(
                await self._load(DatasetDocumentation, run.documentation_id)
            )
        reference = settings.youtube_research_credentials.get(self.workspace_id)
        if not reference and (settings.is_development or settings.is_test):
            reference = settings.youtube_research_local_credential_ref
        if not reference:
            raise ResearchNotConfigured()
        settings.validate_youtube_research_configuration()
        context = CollectionContext(
            workspace_id=self.workspace_id,
            provider_id=source.id,
            provider_key="youtube",
            collection_run_id=run.id,
            dataset_version_id=version.id,
        )
        try:
            store = build_credential_store(settings)
        except Exception:
            # Google SDK/ADC errors may include paths or credential details.
            raise CredentialStoreUnavailableError("startup") from None
        adapter = YouTubeAdapter()
        adapter.gate = RequestGate()
        adapter.quota = YouTubeQuota(
            async_sessionmaker(self.session.bind, expire_on_commit=False),
            spacing=not settings.is_test,
        )
        client = ProviderClient(
            adapter,
            ProviderConfiguration(
                workspace_id=self.workspace_id,
                provider_id=source.id,
                provider_key="youtube",
                credential_ref=reference,
            ),
            credential_store=store,
        )
        return CachedYouTubeClient(client), context
