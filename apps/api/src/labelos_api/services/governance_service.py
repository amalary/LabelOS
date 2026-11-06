"""Composable, authenticated governance operations; the caller commits/rolls back.

Use with caller-owned repository writes in new A&R or Analytics adapters.
Existing Analytics ingestion does not require governance records.
"""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from labelos_database.models import (
    AnalyticsProvider,
    CollectionRun,
    Dataset,
    DatasetDocumentation,
    DatasetLineage,
    DatasetTransformation,
    DatasetVersion,
    GovernanceActivity,
    User,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.authorization import (
    AuthorizationActorInput,
    AuthorizationResource,
    Capability,
    ResourceKind,
    authorization_service,
)
from labelos_api.governance import (
    CollectionRunCreate,
    CollectionRunProgress,
    CollectionRunTransition,
    DatasetCreate,
    Datasheet,
    DocumentationCreate,
    DocumentationTransition,
    SourceRecord,
    SourceRegistration,
    TransformationCreate,
    VersionCreate,
    VersionTransition,
    documentation_issues,
    validate_production,
)
from labelos_api.realtime import RealtimeEventType, RealtimePublisher
from labelos_api.repositories import analytics


class GovernanceError(ValueError):
    pass


class GovernanceNotFound(GovernanceError):
    pass


class GovernanceConflict(GovernanceError):
    pass


class GovernanceForbidden(GovernanceError):
    pass


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class GovernanceService:
    """Shared boundary for departments. An explicit actor is always required."""

    _read_filters = {
        Dataset: frozenset({"provider_id", "owner_department"}),
        DatasetVersion: frozenset({"dataset_id", "state"}),
        DatasetDocumentation: frozenset({"version_id", "state"}),
        CollectionRun: frozenset(
            {
                "documentation_id",
                "source_id",
                "version_id",
                "job_id",
                "retry_of_id",
                "status",
            }
        ),
        DatasetTransformation: frozenset({"output_version_id"}),
        DatasetLineage: frozenset({"transformation_id", "input_version_id"}),
        GovernanceActivity: frozenset({"entity_id"}),
        AnalyticsProvider: frozenset(),
    }

    def __init__(
        self,
        session: AsyncSession,
        workspace_id: UUID,
        *,
        actor: AuthorizationActorInput,
    ):
        if actor is None:
            raise GovernanceForbidden("An authenticated actor is required")
        self.session = session
        self.workspace_id = workspace_id
        self.actor = actor
        self._authorized_actor = None

    async def _decision(self, *, write=False):
        return await authorization_service.decide_capability(
            self.session,
            actor=self.actor,
            workspace=self.workspace_id,
            capability=(
                Capability.governance_manage if write else Capability.governance_view
            ),
            resource=AuthorizationResource(
                kind=ResourceKind.workspace,
                id=self.workspace_id,
                workspace_id=self.workspace_id,
            ),
        )

    async def authorize(self, *, write=False):
        decision = await self._decision(write=write)
        if not decision.allowed:
            raise GovernanceForbidden(decision.reason)
        self._authorized_actor = decision.actor

    @staticmethod
    def _source_record(row, *, details=False):
        result = SourceRecord.model_validate(row)
        return (
            result
            if details
            else result.model_copy(update={"external_account_id": None})
        )

    async def _read_result(self, model, rows):
        if model is AnalyticsProvider:
            details = (await self._decision(write=True)).allowed
            return [self._source_record(row, details=details) for row in rows]
        return rows

    def _require_read_model(self, model):
        if model not in self._read_filters:
            raise GovernanceError("Unsupported governance resource")

    def actor_identity(self):
        user = (
            self.actor
            if isinstance(self.actor, User)
            else getattr(self.actor, "user", None)
        )
        ref = self._authorized_actor
        if ref is None or not ref.subject:
            raise GovernanceForbidden("An attributable actor is required")
        return user, str(ref.kind), ref.subject

    async def _load(self, model, identifier, *, lock=False):
        query = select(model).where(
            model.id == identifier, model.organization_id == self.workspace_id
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = await self.session.scalar(query)
        if row is None:
            raise GovernanceNotFound("Governance resource not found in workspace")
        return row

    async def _record(self, action, row):
        user, kind, key = self.actor_identity()
        actor = self._authorized_actor
        if user is None and actor is not None and actor.user_id is not None:
            user = await self.session.get(User, actor.user_id)
        await self.session.flush()
        activity = GovernanceActivity(
            organization_id=self.workspace_id,
            action=action,
            entity_id=row.id,
            actor_kind=kind,
            actor_key=key,
        )
        self.session.add(activity)
        await self.session.flush()
        await RealtimePublisher(self.session).publish(
            organization_id=self.workspace_id,
            event_type=RealtimeEventType.governance_changed,
            actor=user,
            entity_type=row.__tablename__,
            entity_id=row.id,
            operation_id=str(activity.id),
            payload={"action": action, "activityId": str(activity.id)},
        )
        if isinstance(row, CollectionRun):
            await self.session.refresh(row, attribute_names=["source_id", "version_id"])
        return row

    async def register_source(self, payload: SourceRegistration):
        await self.authorize(write=True)
        existing = await analytics.get_provider_by_key(
            self.session, self.workspace_id, payload.key
        )
        if existing is None:
            # The canonical registry is also written by Analytics. Let its unique
            # constraint arbitrate races without aborting the caller transaction.
            # A conflict-safe insert also avoids releasing a first-write SQLite
            # savepoint, which can commit independently in legacy transaction mode.
            insert = (
                sqlite_insert
                if self.session.get_bind().dialect.name == "sqlite"
                else pg_insert
            )
            source = await self.session.scalar(
                insert(AnalyticsProvider)
                .values(
                    organization_id=self.workspace_id,
                    **payload.model_dump(),
                    metadata_json={},
                )
                .on_conflict_do_nothing(index_elements=["organization_id", "key"])
                .returning(AnalyticsProvider)
            )
            if source is not None:
                await self._record("source.registered", source)
                return self._source_record(source, details=True)
            existing = await analytics.get_provider_by_key(
                self.session, self.workspace_id, payload.key
            )
            if existing is None:
                raise GovernanceConflict("Source registration changed; retry")
        if existing:
            if any(
                getattr(existing, name) != getattr(payload, name)
                for name in ("display_name", "provider_type", "external_account_id")
            ):
                raise GovernanceConflict(
                    "Source key is already registered with different attributes"
                )
            return self._source_record(existing, details=True)

    async def create_dataset(self, payload: DatasetCreate):
        await self.authorize(write=True)
        await self._load(AnalyticsProvider, payload.provider_id)
        dataset = Dataset(organization_id=self.workspace_id, **payload.model_dump())
        self.session.add(dataset)
        return await self._record("dataset.created", dataset)

    async def create_version(self, dataset_id: UUID, payload: VersionCreate):
        await self.authorize(write=True)
        await self._load(Dataset, dataset_id, lock=True)
        if await self.session.scalar(
            select(DatasetVersion.id).where(
                DatasetVersion.dataset_id == dataset_id,
                DatasetVersion.version_key == payload.version_key,
            )
        ):
            raise GovernanceConflict("Version key already exists")
        if payload.parent_version_id:
            parent = await self._load(DatasetVersion, payload.parent_version_id)
            if parent.dataset_id != dataset_id or parent.state == "draft":
                raise GovernanceError(
                    "Parent must be a finalized version of this dataset"
                )
        version = DatasetVersion(
            organization_id=self.workspace_id,
            dataset_id=dataset_id,
            **payload.model_dump(),
        )
        self.session.add(version)
        return await self._record("version.created", version)

    async def transition_version(self, version_id: UUID, payload: VersionTransition):
        await self.authorize(write=True)
        version = await self._load(DatasetVersion, version_id, lock=True)
        if version.state != payload.expected_state or (
            version.state,
            payload.state,
        ) not in {("draft", "finalized"), ("finalized", "archived")}:
            raise GovernanceConflict("Invalid or stale version lifecycle transition")
        if payload.state == "finalized":
            if any(
                getattr(version, field) is None
                for field in (
                    "schema_version",
                    "data_fingerprint",
                    "collection_start",
                    "collection_end",
                    "source_references",
                )
            ):
                raise GovernanceError("Finalization requires complete version metadata")
            version.finalized_at = datetime.now(UTC)
        else:
            version.archived_at = datetime.now(UTC)
        version.state = payload.state
        return await self._record(f"version.{payload.state}", version)

    async def _draft_version(self, version_id):
        version = await self._load(DatasetVersion, version_id, lock=True)
        if version.state != "draft":
            raise GovernanceConflict("Finalized version provenance is immutable")
        return version

    async def latest_documentation(self, version_id):
        await self.authorize()
        await self._load(DatasetVersion, version_id)
        return await self._latest_documentation(version_id)

    async def _latest_documentation(self, version_id):
        """Internal lookup after the operation has authorized read or write access."""
        return await self.session.scalar(
            select(DatasetDocumentation)
            .where(
                DatasetDocumentation.organization_id == self.workspace_id,
                DatasetDocumentation.version_id == version_id,
            )
            .order_by(DatasetDocumentation.revision.desc())
            .limit(1)
        )

    async def document_version(self, version_id: UUID, payload: DocumentationCreate):
        await self.authorize(write=True)
        await self._draft_version(version_id)
        previous = await self._latest_documentation(version_id)
        revision = previous.revision if previous else 0
        if payload.expected_revision != revision:
            raise GovernanceConflict("Documentation revision changed")
        eligibility = validate_production(
            payload.document, today=datetime.now(UTC).date()
        )
        if payload.production_eligible and not eligibility.eligible:
            raise GovernanceError(
                "Production eligibility: " + ", ".join(eligibility.issues)
            )
        document = payload.document.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        _, kind, key = self.actor_identity()
        row = DatasetDocumentation(
            organization_id=self.workspace_id,
            version_id=version_id,
            revision=revision + 1,
            state="draft",
            authored_revision=revision + 1,
            document=document,
            document_sha256=digest,
            production_eligible=payload.production_eligible,
            change_reason=payload.change_reason,
            actor_kind=kind,
            actor_key=key,
        )
        self.session.add(row)
        return await self._record("documentation.created", row)

    async def transition_documentation(
        self, version_id: UUID, payload: DocumentationTransition
    ):
        await self.authorize(write=True)
        await self._draft_version(version_id)
        previous = await self._latest_documentation(version_id)
        if previous is None:
            raise GovernanceNotFound("No dataset documentation")
        if payload.expected_revision != previous.revision:
            raise GovernanceConflict("Documentation revision changed")
        if (previous.state, payload.state) not in {
            ("draft", "validated"),
            ("validated", "published"),
        }:
            raise GovernanceConflict("Invalid documentation lifecycle transition")
        document = Datasheet.model_validate(previous.document)
        issues = documentation_issues(document)
        if issues:
            raise GovernanceError("Incomplete documentation: " + ", ".join(issues))
        if previous.production_eligible:
            eligibility = validate_production(document, today=datetime.now(UTC).date())
            if not eligibility.eligible:
                raise GovernanceError(
                    "Production eligibility: " + ", ".join(eligibility.issues)
                )
        _, kind, key = self.actor_identity()
        row = DatasetDocumentation(
            organization_id=self.workspace_id,
            version_id=version_id,
            revision=previous.revision + 1,
            state=payload.state,
            authored_revision=previous.authored_revision or previous.revision,
            document=previous.document,
            document_sha256=previous.document_sha256,
            production_eligible=previous.production_eligible,
            change_reason=payload.change_reason,
            actor_kind=kind,
            actor_key=key,
        )
        self.session.add(row)
        return await self._record(f"documentation.{payload.state}", row)

    async def _production_document(self, document):
        version = await self._load(DatasetVersion, document.version_id, lock=True)
        if version.state == "archived":
            raise GovernanceConflict("Archived versions cannot start production runs")
        latest = await self._latest_documentation(document.version_id)
        if latest is None or latest.id != document.id:
            raise GovernanceConflict("Production runs require the latest documentation")
        result = validate_production(
            Datasheet.model_validate(document.document), today=datetime.now(UTC).date()
        )
        if not document.production_eligible or not result.eligible:
            raise GovernanceError("Documentation is not currently production eligible")

    async def create_run(self, payload: CollectionRunCreate):
        await self.authorize(write=True)
        # Serialize duplicate deliveries and retry creation for this provenance.
        document = await self._load(
            DatasetDocumentation, payload.documentation_id, lock=True
        )
        existing = await self.session.scalar(
            select(CollectionRun).where(
                CollectionRun.organization_id == self.workspace_id,
                CollectionRun.run_key == payload.run_key,
            )
        )
        if existing:
            if (
                existing.documentation_id != payload.documentation_id
                or existing.production != payload.production
                or existing.job_id != payload.job_id
                or existing.retry_of_id != payload.retry_of_id
                or existing.max_attempts != payload.max_attempts
                or (None if existing.not_before is None else _utc(existing.not_before))
                != payload.not_before
            ):
                raise GovernanceConflict("Run key already used with different inputs")
            return existing
        attempt = 1
        checkpoint = None
        if payload.retry_of_id:
            previous = await self._load(CollectionRun, payload.retry_of_id, lock=True)
            if (
                previous.status not in {"failed", "partially_completed"}
                or previous.documentation_id != payload.documentation_id
                or previous.production != payload.production
                or previous.max_attempts != payload.max_attempts
                or previous.attempt >= previous.max_attempts
            ):
                raise GovernanceConflict("Run is not eligible for this retry")
            if await self.session.scalar(
                select(CollectionRun.id).where(
                    CollectionRun.organization_id == self.workspace_id,
                    CollectionRun.retry_of_id == previous.id,
                )
            ):
                raise GovernanceConflict("Run already has a retry attempt")
            attempt = previous.attempt + 1
            checkpoint = previous.checkpoint
        if payload.production:
            await self._production_document(document)
        run = CollectionRun(
            organization_id=self.workspace_id,
            status="queued",
            attempt=attempt,
            checkpoint=checkpoint,
            **payload.model_dump(),
        )
        self.session.add(run)
        return await self._record("collection.queued", run)

    async def transition_run(self, run_id: UUID, payload: CollectionRunTransition):
        await self.authorize(write=True)
        run = await self._load(CollectionRun, run_id, lock=True)
        terminal = {
            "completed",
            "succeeded",
            "partially_completed",
            "failed",
            "cancelled",
        }
        if run.status in terminal and run.status == payload.status:
            if any(
                getattr(run, key) != value
                for key, value in payload.model_dump().items()
            ):
                raise GovernanceConflict(
                    "Completion was already recorded with a different outcome"
                )
            return run
        allowed = {
            "queued": {"running", "cancelled"},
            "running": terminal,
        }
        if payload.status not in allowed.get(run.status, set()):
            raise GovernanceConflict("Invalid collection run transition")
        if (
            run.status == "queued"
            and payload.status == "cancelled"
            and payload.records_seen
        ):
            raise GovernanceError("An unstarted run cannot have collected records")
        if payload.status == "running" and run.production:
            await self._production_document(
                await self._load(DatasetDocumentation, run.documentation_id)
            )
        now = datetime.now(UTC)
        if (
            payload.status == "running"
            and run.not_before
            and now < _utc(run.not_before)
        ):
            raise GovernanceConflict("Run is not due yet")
        self._check_run_counts(run, payload)
        if payload.status == "running":
            run.started_at = now
        else:
            run.completed_at = now
        for key, value in payload.model_dump().items():
            setattr(run, key, value)
        return await self._record(f"collection.{payload.status}", run)

    @staticmethod
    def _check_run_counts(run, payload):
        if any(
            getattr(payload, field) < getattr(run, field)
            for field in ("records_seen", "records_written", "records_rejected")
        ):
            raise GovernanceConflict("Collection counts cannot move backwards")

    async def checkpoint_run(self, run_id: UUID, payload: CollectionRunProgress):
        """Flush with the adapter's data writes; caller owns the transaction."""
        await self.authorize(write=True)
        run = await self._load(CollectionRun, run_id, lock=True)
        if (
            run.status != "running"
            or run.progress_revision != payload.expected_revision
        ):
            raise GovernanceConflict("Invalid or stale collection checkpoint")
        self._check_run_counts(run, payload)
        for field in ("records_seen", "records_written", "records_rejected"):
            setattr(run, field, getattr(payload, field))
        run.checkpoint = payload.checkpoint.model_dump(mode="json")
        run.progress_revision += 1
        return await self._record("collection.checkpointed", run)

    async def record_transformation(self, payload: TransformationCreate):
        await self.authorize(write=True)
        output = await self._draft_version(payload.output_version_id)
        for identifier in payload.input_version_ids:
            source = await self._load(DatasetVersion, identifier)
            if _utc(source.created_at) >= _utc(output.created_at):
                raise GovernanceError("Lineage inputs must precede the output version")
        if payload.collection_run_id:
            run = await self._load(CollectionRun, payload.collection_run_id)
            document = await self._load(DatasetDocumentation, run.documentation_id)
            if (
                run.status not in {"succeeded", "completed"}
                or document.version_id not in payload.input_version_ids
            ):
                raise GovernanceError(
                    "Collection run must succeed and belong to an input version"
                )
        transformation = DatasetTransformation(
            organization_id=self.workspace_id,
            **payload.model_dump(exclude={"input_version_ids"}),
        )
        self.session.add(transformation)
        await self.session.flush()
        self.session.add_all(
            [
                DatasetLineage(
                    organization_id=self.workspace_id,
                    transformation_id=transformation.id,
                    input_version_id=identifier,
                )
                for identifier in payload.input_version_ids
            ]
        )
        return await self._record("transformation.created", transformation)

    async def list_records(self, model, *, limit=100, offset=0, **filters):
        await self.authorize()
        self._require_read_model(model)
        if filters.keys() - self._read_filters[model]:
            raise GovernanceError("Unsupported governance filter")
        if not 1 <= limit <= 500 or offset < 0:
            raise GovernanceError("Invalid pagination")
        query = select(model).where(model.organization_id == self.workspace_id)
        for name, value in filters.items():
            if value is not None:
                query = query.where(getattr(model, name) == value)
        ordering = (
            (model.revision, model.id)
            if model is DatasetDocumentation
            else (model.created_at, model.id)
        )
        rows = list(
            await self.session.scalars(
                query.order_by(*ordering).limit(limit).offset(offset)
            )
        )
        return await self._read_result(model, rows)

    async def get_record(self, model, identifier):
        await self.authorize()
        self._require_read_model(model)
        rows = await self._read_result(model, [await self._load(model, identifier)])
        return rows[0]

    async def eligibility(self, version_id: UUID):
        await self.authorize()
        version = await self._load(DatasetVersion, version_id)
        document = await self._latest_documentation(version_id)
        if not document:
            raise GovernanceNotFound("No dataset documentation")
        result = validate_production(
            Datasheet.model_validate(document.document), today=datetime.now(UTC).date()
        )
        if not document.production_eligible:
            result.issues.append("production_not_requested")
            result.eligible = False
        if version.state == "archived":
            result.issues.append("version_archived")
            result.eligible = False
        return result
