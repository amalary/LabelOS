# Transformation lineage

Record provenance uses three tables in the existing database: immutable record
snapshots, transformation events, and input-to-output edges. Dataset-level
`DatasetTransformation` / `DatasetLineage` remain compatible. Record provenance
adds the detail needed to trace an output to individual collected records.

## Recording data

Use `ProvenanceService(session, workspace_id, actor=authenticated_actor)` inside
the adapter transaction. The caller owns commit/rollback, just as with
`GovernanceService`. Raw registration and each transformation create permanent
governance activity and transactional realtime outbox events containing IDs and
fixed actions only.

1. Persist the source record in its approved store and call `register_raw` with
   its opaque UUID locator, dataset version, collection run, and optional SHA-256.
   The run must be running, completed, succeeded, or partially completed, and
   must belong to that version. No payloads, URLs, credentials, or provider keys
   are accepted by the provenance contract.
2. Call `transform` with input record IDs, output specifications, a dataset
   version, transformation type, and an immutable code/model version identifier.
   An optional collection run must belong to an input version. Every source run
   also remains reachable through the input graph, including multi-source runs.
3. `normalize` connects raw records to a workspace artist snapshot; `transform`
   creates observations, optionally bound to an existing `AnalyticsObservation`;
   `derive` creates output snapshots. The returned record ID is the durable
   reference for each output. One event can have multiple inputs and outputs;
   every listed output depends on every listed input. Use separate events when
   outputs have different dependencies.
4. `merge` takes at least two normalized snapshots and creates one new snapshot
   bound to the surviving artist. Include the survivor's previous snapshot as an
   input when merging into an existing identity. Previous snapshots, observations,
   outputs, edges, and artist IDs remain unchanged. Commit this operation in the
   same transaction as any canonical identity updates made by the caller.

Repeated processing creates a new event and new outputs, preserving code-version
history. Adapters should retain returned IDs and handle delivery deduplication in
their transaction; this API does not infer idempotency from matching inputs.
Existing analytics ingestion remains compatible. It does not invent provenance
for historical records without source evidence; governed adapters explicitly
record their lineage alongside their data writes.

## Querying

Under `/api/v1/workspaces/{workspace_id}/governance/provenance`:

- POST `/records`: register a raw record.
- POST `/transformations`: atomically record an event, new output records, and
  edges. Returns the event, input references, and output references.
- GET `/records`: paginated snapshots, optionally filtered by `artist_id` or
  `observation_id`. This provides an entry point from application entities.
- GET `/records/{id}/lineage`: traverse `direction=ancestors` (default) or
  `direction=descendants`. Returns records, timestamped edges, and events with
  type, version, dataset version, optional run, timestamp, and actor attribution.

Traversal defaults to 50 levels and 1,000 nodes (maximum 100 levels / 1,000 nodes).
`truncated` explicitly marks incomplete results due to depth or node bounds.
The total edge budget is 10,000; excessive fan-out returns 409. Missing ancestors,
unavailable references, and corrupt ordering return 409 rather than an apparently
complete graph. Unknown or foreign roots return 404 after workspace authorization.

Reads require `governance.view`; writes require `governance.manage`, including
agent callers using the existing authorization service. Source locators and
content digests are redacted by default. `include_source_details=true` additionally
requires `governance.manage`. This returns metadata only; resolving a locator and
reading a provider payload still requires the source store's own authorization.

## History and database guarantees

Migration `202610120500` adds the graph without rewriting existing evidence.
Workspace-composite foreign keys scope all graph, dataset, and run references.
Insert guards validate run/version and entity ownership. UPDATE and DELETE are
rejected on all three tables, including direct SQL. Increasing immutable
generation numbers enforce a DAG independently of clocks and concurrent writers.
New lineage requires a draft output dataset version. PostgreSQL row locks
serialize provenance insertion with version finalization; finalized and archived
versions retain their existing queryable history.
All edges have their own creation timestamps, so any privileged SQL append is
visible in history; there is no API to append edges to an existing output.
Artist/observation IDs are historical bindings checked at insertion, not cascading
foreign keys: later canonical deletion or merging cannot erase their provenance.

Only migration/DB administration can disable these guards. Traversal detects
missing ancestry and invalid ordering in imported or damaged graphs as well.
Downgrade refuses to discard nonempty provenance tables. SQLite and PostgreSQL
tests cover the graph, merge history, API permissions, direct SQL guards, and
migration schema parity.
