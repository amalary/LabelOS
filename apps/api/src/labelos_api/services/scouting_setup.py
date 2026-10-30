"""Explicit local exploration setup through the existing governance boundary."""

from uuid import uuid4

from labelos_database.models import (
    AnalyticsProvider,
    CollectionRun,
    DatasetVersion,
    Organization,
)
from sqlalchemy import select

from labelos_api.governance import (
    CollectionRunCreate,
    CollectionRunTransition,
    DatasetCreate,
    Datasheet,
    DocumentationCreate,
    SourceRegistration,
    VersionCreate,
)
from labelos_api.services.governance_service import GovernanceService


async def prepare_local_session(session, workspace_id, actor):
    service = GovernanceService(session, workspace_id, actor=actor)
    await service.authorize(write=True)
    # Serialize setup within this workspace; no membership or permission changes.
    await session.scalar(
        select(Organization).where(Organization.id == workspace_id).with_for_update()
    )
    existing = await session.scalar(
        select(CollectionRun)
        .join(AnalyticsProvider, CollectionRun.source_id == AnalyticsProvider.id)
        .join(DatasetVersion, CollectionRun.version_id == DatasetVersion.id)
        .where(
            CollectionRun.organization_id == workspace_id,
            AnalyticsProvider.organization_id == workspace_id,
            DatasetVersion.organization_id == workspace_id,
            AnalyticsProvider.key == "youtube",
            CollectionRun.status == "running",
            CollectionRun.production.is_(False),
            DatasetVersion.state != "archived",
        )
        .order_by(CollectionRun.created_at.desc())
        .limit(1)
    )
    if existing:
        return existing, False
    source = await session.scalar(
        select(AnalyticsProvider).where(
            AnalyticsProvider.organization_id == workspace_id,
            AnalyticsProvider.key == "youtube",
        )
    )
    if source is None:
        source = await service.register_source(
            SourceRegistration(
                key="youtube", display_name="YouTube", provider_type="public_api"
            )
        )
    key = "local-youtube-scouting-" + uuid4().hex
    dataset = await service.create_dataset(
        DatasetCreate(
            key=key,
            display_name="Local YouTube scouting",
            provider_id=source.id,
            owner_department="a&r",
        )
    )
    version = await service.create_version(dataset.id, VersionCreate(version_key="v1"))
    document = await service.document_version(
        version.id,
        DocumentationCreate(
            expected_revision=0,
            production_eligible=False,
            change_reason="Prepare an explicitly requested local exploration session",
            document=Datasheet(
                motivation="Local, human-led A&R workflow verification",
                collection="Explicit bounded public YouTube Data API requests",
                intended_uses=["Display current channel facts and save human review"],
                prohibited_uses=[
                    "Derived scores, historical counters, scraping or bulk collection"
                ],
                limitations="Draft local exploration; no production or policy approval",
                terms_reference="https://developers.google.com/youtube/terms/developer-policies",
                license_approved=False,
                privacy_reviewed=False,
            ),
        ),
    )
    run = await service.create_run(
        CollectionRunCreate(documentation_id=document.id, run_key=key, production=False)
    )
    await service.transition_run(run.id, CollectionRunTransition(status="running"))
    return run, True
