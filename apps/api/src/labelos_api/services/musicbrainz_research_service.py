"""Authorized public metadata tied to a workspace's running collection."""

from uuid import UUID

from labelos_database.models import (
    AnalyticsProvider,
    CollectionRun,
    DatasetDocumentation,
    DatasetVersion,
)

from labelos_api.config import Settings
from labelos_api.research.contracts import CollectionContext
from labelos_api.research.musicbrainz import build_musicbrainz_client
from labelos_api.services.governance_service import (
    GovernanceConflict,
    GovernanceService,
)
from labelos_api.services.scouting_service import authorize_scout


class MusicBrainzResearchService(GovernanceService):
    async def client_for_run(self, run_id: UUID, settings: Settings):
        await authorize_scout(self.session, self.workspace_id, self.actor)
        run = await self._load(CollectionRun, run_id, lock=True)
        if run.status != "running":
            raise GovernanceConflict("MusicBrainz requires a running collection")
        source = await self._load(AnalyticsProvider, run.source_id)
        if source.key != "musicbrainz":
            raise GovernanceConflict("Collection source must be MusicBrainz")
        version = await self._load(DatasetVersion, run.version_id, lock=True)
        if version.state == "archived":
            raise GovernanceConflict("Archived versions cannot collect data")
        if not run.production and settings.requires_strict_startup_validation:
            raise GovernanceConflict("Production requires a production collection")
        if run.production:
            await self._production_document(
                await self._load(DatasetDocumentation, run.documentation_id)
            )
        context = CollectionContext(
            workspace_id=self.workspace_id,
            provider_id=source.id,
            provider_key="musicbrainz",
            collection_run_id=run.id,
            dataset_version_id=version.id,
        )
        return build_musicbrainz_client(settings, context), context
