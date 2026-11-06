"""Authenticated provenance writes and bounded graph traversal.

Adapters call these operations in the same transaction as their data writes.
Every output is a new immutable snapshot; merge never rewrites older identities.
"""

from labelos_database.models import (
    AnalyticsObservation,
    Artist,
    CollectionRun,
    ProvenanceEdge,
    ProvenanceRecord,
    ProvenanceTransformation,
)
from sqlalchemy import select

from labelos_api.provenance import (
    EdgeResponse,
    ProvenanceGraph,
    RawRecordCreate,
    RecordResponse,
    RecordTransformationCreate,
    TransformationResponse,
    TransformationResult,
)
from labelos_api.services.governance_service import (
    GovernanceConflict,
    GovernanceError,
    GovernanceService,
)


class ProvenanceService(GovernanceService):
    async def _run(self, identifier):
        run = await self._load(CollectionRun, identifier)
        if run.status not in {
            "running",
            "completed",
            "succeeded",
            "partially_completed",
        }:
            raise GovernanceError("Collection run has no usable collection data")
        return run

    @staticmethod
    def _record_response(row, details=False):
        result = RecordResponse.model_validate(row)
        if not details:
            result.source_reference = None
            result.content_sha256 = None
        return result

    async def register_raw(self, payload: RawRecordCreate):
        await self.authorize(write=True)
        await self._draft_version(payload.version_id)
        run = await self._run(payload.collection_run_id)
        if run.version_id != payload.version_id:
            raise GovernanceError("Source record must belong to the collection version")
        row = ProvenanceRecord(
            organization_id=self.workspace_id,
            kind="raw_source",
            generation=0,
            **payload.model_dump(),
        )
        self.session.add(row)
        await self._record("provenance.source_registered", row)
        return self._record_response(row, True)

    async def transform(self, payload: RecordTransformationCreate):
        await self.authorize(write=True)
        await self._draft_version(payload.version_id)
        inputs = [await self._load(ProvenanceRecord, i) for i in payload.input_ids]
        if payload.transformation_type == "merge" and any(
            i.kind != "normalized_artist" for i in inputs
        ):
            raise GovernanceError("Only normalized artist identities can be merged")
        if payload.transformation_type == "normalize" and any(
            i.kind != "raw_source" for i in inputs
        ):
            raise GovernanceError("Normalization requires raw source records")
        if payload.collection_run_id:
            run = await self._run(payload.collection_run_id)
            if run.version_id not in {i.version_id for i in inputs}:
                raise GovernanceError(
                    "Transformation run must belong to an input version"
                )
        for output in payload.outputs:
            if output.artist_id:
                await self._load(Artist, output.artist_id)
            if output.observation_id:
                await self._load(AnalyticsObservation, output.observation_id)
        _, actor_kind, actor_key = self.actor_identity()
        # Validation completes before writes; the savepoint also makes this safe
        # for worker callers that catch an insertion failure and continue work.
        async with self.session.begin_nested():
            transformation = ProvenanceTransformation(
                organization_id=self.workspace_id,
                actor_kind=actor_kind,
                actor_key=actor_key,
                **payload.model_dump(exclude={"input_ids", "outputs"}),
            )
            self.session.add(transformation)
            await self.session.flush()
            outputs = [
                ProvenanceRecord(
                    organization_id=self.workspace_id,
                    version_id=payload.version_id,
                    transformation_id=transformation.id,
                    generation=max(i.generation for i in inputs) + 1,
                    **output.model_dump(),
                )
                for output in payload.outputs
            ]
            self.session.add_all(outputs)
            await self.session.flush()
            self.session.add_all(
                [
                    ProvenanceEdge(
                        organization_id=self.workspace_id,
                        input_id=i.id,
                        output_id=o.id,
                    )
                    for i in inputs
                    for o in outputs
                ]
            )
            await self._record("provenance.transformed", transformation)
        return TransformationResult(
            transformation=TransformationResponse.model_validate(transformation),
            inputs=payload.input_ids,
            outputs=[self._record_response(o, True) for o in outputs],
        )

    async def records(
        self, *, artist_id=None, observation_id=None, limit=100, offset=0
    ):
        await self.authorize()
        if not 1 <= limit <= 500 or offset < 0:
            raise GovernanceError("Invalid pagination")
        query = select(ProvenanceRecord).where(
            ProvenanceRecord.organization_id == self.workspace_id
        )
        if artist_id is not None:
            query = query.where(ProvenanceRecord.artist_id == artist_id)
        if observation_id is not None:
            query = query.where(ProvenanceRecord.observation_id == observation_id)
        rows = await self.session.scalars(
            query.order_by(ProvenanceRecord.created_at, ProvenanceRecord.id)
            .limit(limit)
            .offset(offset)
        )
        return [self._record_response(row) for row in rows]

    async def traverse(
        self,
        record_id,
        *,
        direction="ancestors",
        max_depth=50,
        max_nodes=1000,
        include_source_details=False,
    ):
        await self.authorize()
        if include_source_details:
            # governance.view grants graph metadata, not source-store locators.
            await self.authorize(write=True)
        if (
            direction not in {"ancestors", "descendants"}
            or not 1 <= max_depth <= 100
            or not 1 <= max_nodes <= 1000
        ):
            raise GovernanceError("Invalid traversal bounds")
        root = await self._load(ProvenanceRecord, record_id)
        nodes, edges = {root.id: root}, {}
        frontier = {root.id}
        truncated = False
        for depth in range(max_depth + 1):
            column = (
                ProvenanceEdge.output_id
                if direction == "ancestors"
                else ProvenanceEdge.input_id
            )
            batch = list(
                await self.session.scalars(
                    select(ProvenanceEdge)
                    .where(
                        ProvenanceEdge.organization_id == self.workspace_id,
                        column.in_(frontier),
                    )
                    .order_by(ProvenanceEdge.created_at, ProvenanceEdge.id)
                    .limit(10001)
                )
            )
            if len(edges) + len(batch) > 10000:
                raise GovernanceConflict("Lineage fan-out exceeds traversal budget")
            if direction == "ancestors":
                linked = {e.output_id for e in batch}
                if any(
                    nodes[i].kind != "raw_source" and i not in linked for i in frontier
                ):
                    raise GovernanceConflict("Lineage is missing ancestors")
            if depth == max_depth:
                truncated = bool(batch)
                break
            identifiers = {
                e.input_id if direction == "ancestors" else e.output_id for e in batch
            }
            unseen = identifiers - nodes.keys()
            if len(nodes) + len(unseen) > max_nodes:
                truncated = True
                break
            loaded = (
                list(
                    await self.session.scalars(
                        select(ProvenanceRecord).where(
                            ProvenanceRecord.organization_id == self.workspace_id,
                            ProvenanceRecord.id.in_(unseen),
                        )
                    )
                )
                if unseen
                else []
            )
            if len(loaded) != len(unseen):
                # Never disclose identifiers or details from another workspace.
                raise GovernanceConflict("Lineage contains unavailable references")
            nodes.update({n.id: n for n in loaded})
            for edge in batch:
                if nodes[edge.input_id].generation >= nodes[edge.output_id].generation:
                    raise GovernanceConflict(
                        "Lineage contains a cycle or invalid ordering"
                    )
                edges[edge.id] = edge
            frontier = unseen
            if not frontier:
                break
        transformation_ids = {n.transformation_id for n in nodes.values()} - {None}
        transformations = list(
            await self.session.scalars(
                select(ProvenanceTransformation)
                .where(
                    ProvenanceTransformation.organization_id == self.workspace_id,
                    ProvenanceTransformation.id.in_(transformation_ids),
                )
                .order_by(
                    ProvenanceTransformation.created_at, ProvenanceTransformation.id
                )
            )
        )
        if len(transformations) != len(transformation_ids):
            raise GovernanceConflict("Lineage contains unavailable transformations")
        return ProvenanceGraph(
            root_id=record_id,
            direction=direction,
            records=[
                self._record_response(n, include_source_details)
                for n in sorted(nodes.values(), key=lambda n: (n.generation, str(n.id)))
            ],
            edges=[EdgeResponse.model_validate(e) for e in edges.values()],
            transformations=[
                TransformationResponse.model_validate(t) for t in transformations
            ],
            truncated=truncated,
        )
