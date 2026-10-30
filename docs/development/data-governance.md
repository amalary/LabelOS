# Cross-department data governance

This stage implements dataset documentation and provenance based on
[Datasheets for Datasets, Gebru et al.](https://arxiv.org/abs/1803.09010).
The datasheet covers motivation, composition, collection, preprocessing, uses,
distribution and maintenance, with explicit limitations, licensing, privacy and
retention controls. It is a review record, not a substitute for a provider terms
review or an assertion that the data is representative.

## Storage and boundaries

Migration `202610120100` follows the prior Alembic head `202609210100`.
Migration `202610120200` adds documentation lifecycle and content authorship
references without rewriting existing documents, digests, or collection-run links.
Workspace APIs use `workspace_id`; database ownership uses `organization_id`,
as in Analytics. Composite foreign keys prevent cross-workspace provenance.

- `analytics_providers` remains the only provider/source registry. Registration
  reuses existing records by workspace and key; incompatible attributes conflict.
  No metric catalog is introduced. `analytics_metric_definitions` remains canonical.
- `datasets` describes a named source-backed dataset and its owning department.
  Department ownership is descriptive; it does not restrict reuse to that department.
- `dataset_versions` identifies a data/schema release independently of documentation.
- `dataset_documentation` appends numbered, attributed datasheet revisions with a
  change reason and canonical SHA-256 digest. Optimistic `expected_revision` checks
  plus a version-row lock prevent lost revisions. A documentation correction on a draft data version does
  not require creating a new dataset version. Finalized data versions freeze this history.
- `collection_runs` pins an exact documentation revision and records lifecycle,
  timestamps, counts and an allowlisted error category. A workspace-scoped run key
  makes repeated creation idempotent; conflicting inputs return 409.
- `dataset_transformations` and `dataset_lineage` retain code references, optional
  parameter digests, input versions, output versions and a successful input run.
  An output has one producing transformation. Inputs must be created before the
  output version; this also prevents cycles. Register imported histories in
  topological order. List endpoints expose both upstream and downstream edges.
- `governance_activity` retains immutable actor/action/entity facts. The same
  transaction queues an identifier-only `governance.changed` event in the existing
  `RealtimeEvent` outbox. Event delivery or pruning does not delete audit history.

Database triggers reject changes/deletion of documentation and provenance, and
invalid or repeated terminal run transitions. Corrections append a new revision
or version. These records also block accidental removal of referenced sources.
There is no destructive governance API in this stage.

## Production eligibility and retention

Draft datasheets may be incomplete. A production-eligible revision requires every
core section, intended uses, a maintainer, an explicit retention policy, approved
licensing, reviewed privacy, a terms reference, and a current bounded terms review.
Eligibility is checked again when a production run starts, using the latest
revision. Appending an ineligible revision revokes new production collection for
that version; historical runs continue to reference their original documentation.
Revocation does not interrupt an already running external collector in this stage.

Raw storage defaults to **prohibited**. When explicitly permitted, raw storage
must have a finite positive retention period. Derived data also has a bounded
retention period, a deletion process, and a documented lineage retention policy.
This feature does not store raw payloads or implement provider-side deletion jobs.
Adapters must enforce these policies in their own storage before collecting data.
Do not put credentials, personal records, signed payload URLs, raw error messages,
or sensitive raw-payload hashes into immutable documentation/provenance fields.
Code references and parameter digests describe processing, not personal records.
Historical lineage can therefore remain useful after permitted raw storage expires.

## API and authorization

Routes are under `/api/v1/workspaces/{workspace_id}/governance`:

| Resource                                       | Operations                                           |
| ---------------------------------------------- | ---------------------------------------------------- |
| `/sources`                                     | Register/reuse and list canonical providers          |
| `/datasets` and `/datasets/{id}`               | Create, filter/list and retrieve datasets            |
| `/datasets/{id}/versions`                      | Create and list data versions                        |
| `/versions/{id}/documentation`                 | Append and list documentation history                |
| `/versions/{id}/documentation/transitions`     | Validate or publish the latest documentation         |
| `/documentation/{id}`                          | Retrieve an exact historical revision                |
| `/versions/{id}/eligibility`                   | Evaluate the latest revision now                     |
| `/collection-runs` and `/collection-runs/{id}` | Create, list and retrieve runs                       |
| `/collection-runs/{id}/transitions`            | Start, succeed, fail or cancel                       |
| `/transformations`                             | Record and filter/list transformations               |
| `/lineage`                                     | Filter/list edges by transformation or input version |
| `/activity`                                    | Filter/list durable audit facts by entity            |

Lists use `limit` (1–500) and `offset`. All routes require authentication and
database-backed workspace membership. `governance.view` reads; `governance.manage`
writes. Neither capability imposes an Analytics department restriction. Default
owner/admin roles receive both; member, A&R, manager, marketing, legal and finance
roles receive view. Custom roles can delegate either using existing role tools.
Write permission alone does not implicitly grant read permission.

All public service reads, including `latest_documentation`, enforce
`governance.view` using `AuthorizationService.decide_capability`. Internal
documentation lookups run only after the enclosing read or mutation authorizes
its capability. Generic reads accept only the governance model allowlist; they
cannot retrieve artists, credentials, or raw provenance records under a governance
grant. Record lineage uses its dedicated service and redacted response contracts.

| Action                                                                                                                             | Required capabilities                     |
| ---------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Read datasets, versions, documentation, runs, activity, or redacted lineage                                                        | `governance.view`                         |
| Register sources, create datasets/versions, author/validate/publish documentation, finalize/archive versions, collect or transform | `governance.manage`                       |
| Read restricted source account IDs or request lineage source locators/hashes                                                       | `governance.view` and `governance.manage` |

The A&R capabilities (`ar.scouting.*`, `ar.evaluation.*`, `ar.signing.approve`)
and Analytics capabilities (`analytics.view`, `analytics.create`) do not substitute
for governance grants. Role names or claims alone cannot authorize an operation;
the central resolver reads active workspace memberships and their persisted grants.
Dataset department labels remain descriptive, so shared governance can be used
across departments without granting unrelated department operations.

Source operations return an explicit `SourceRecord` projection rather than an ORM
provider. Provider metadata and credential-bearing relationships are never exposed
through governance, including to managers. Read-only viewers receive a null
`external_account_id`; authorized managers receive the account identifier. This
projection does not modify the canonical Analytics provider. Source registration
rejects undeclared metadata/credential fields, and validation errors omit submitted
values. Arbitrary prose still must not contain secrets: governance is not a secret
store or a general-purpose secret detector.

Workspace-scoped loads validate local resource IDs; composite foreign keys and
database guards also enforce nested ownership. Missing and foreign IDs have the
same 404 result, while collection filters over foreign IDs return no matching rows.
External `job_id`, `source_reference`, and `cursor_reference` UUIDs are opaque
adapter references, not local scheduling-job or credential access grants. Adapters
must independently authorize their external stores before resolving those IDs.
Sensitive mutations retain their actor/action/entity audit and identifier-only
outbox event in the same transaction; rejected writes create neither.

## A&R datasheets and review lifecycle

The existing `Datasheet` contract now covers all A&R documentation sections:

| Requirement                    | Datasheet field                                       |
| ------------------------------ | ----------------------------------------------------- |
| Purpose                        | `motivation`                                          |
| Provenance and upstream origin | `provenance`, `origin`                                |
| Source release or snapshot     | `source_version`                                      |
| Collection methodology         | `collection`, `preprocessing`                         |
| Ownership and stewardship      | `ownership`, `maintainer`                             |
| Licensing and permitted use    | `licensing`, `intended_uses`, `prohibited_uses`       |
| Composition and coverage       | `composition`, `coverage`                             |
| Update frequency               | `update_frequency`, `maintenance`                     |
| Known limitations and biases   | `limitations`, `biases`                               |
| Privacy and retention          | `privacy`, `retention`                                |
| Schema and field descriptions  | `dataset_schema.description`, `dataset_schema.fields` |

Each schema field requires a unique `name`, `data_type`, `description`, `nullable`
flag, and `privacy_classification` (`non_personal`, `personal`, or `sensitive`).
The dataset version links to its dataset and canonical source (`provider_id`);
`source_version` records that provider's release/snapshot reference. This does not
introduce another source registry. Use explicit descriptions for unknown coverage
or unassessed biases rather than leaving review sections blank.

Creating or correcting documentation always appends a **draft**. Drafts may be
partial; supplied fields still enforce types, nonblank text, and schema integrity.
The transition endpoint accepts `state`, `expected_revision`, and `change_reason`:

```json
{ "state": "validated", "expected_revision": 1, "change_reason": "Steward review completed" }
```

Only **draft → validated → published** is allowed. Both transitions require all
sections listed above (except optional `prohibited_uses`), plus `distribution`.
They copy the exact stored content and digest into a new numbered immutable
revision. A validated document cannot be edited and then published under its old
review: a correction appends a draft and requires validation again. Repeated,
skipped, backward, or stale transitions return 409; incomplete review content
returns 400; malformed request fields return 422.

Every revision's `actor_kind`, `actor_key`, and `created_at` identify its author,
validator, or publisher according to its state. `authored_revision` points to the
draft that authored the content within the same dataset version. Its actor and
timestamp remain available even when a different person validates or publishes.
Transitions and new drafts also append permanent audit facts and outbox events in
the same transaction. `governance.manage` is required for all these writes.

History lists are ordered by revision, support pagination and an optional `state`
filter, and include old publications after later corrections. Exact-ID reads use
`governance.view` and workspace scoping. Database guards prohibit UPDATE/DELETE
of every revision, including published content, authorship, and timestamps.

Existing documentation migrates to `draft` without claiming a historical review;
its null `authored_revision` means the record itself authored its content. Existing
production eligibility remains a separate, time-sensitive collection control for
compatibility with earlier governance adapters. Publication does not grant
production permission. Transitions recheck terms/privacy/license eligibility when
the copied revision requests production eligibility. New production runs still
require the latest exact revision, including after a documentation transition.

## Reproducible dataset versions

Migration `202610120300` extends the existing `dataset_versions` table. Its
server-generated UUID `id` is the immutable reference for scouting results and
future agent runs. `version_key` is unique within the dataset and never reused;
new releases create new rows. Neither metadata nor identifiers can be edited,
even in draft, preserving the governance foundation's immutable records.

Create a version with `POST /datasets/{dataset_id}/versions`:

```json
{
  "version_key": "signals-2026-10-02",
  "schema_version": "artist-signals/2",
  "data_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "collection_start": "2026-10-01T00:00:00Z",
  "collection_end": "2026-10-02T00:00:00Z",
  "source_references": ["provider:export/2026-10-02"],
  "parent_version_id": null
}
```

`schema_version` identifies the data schema, independently of the datasheet
contract's `schema_version`. `data_fingerprint` is a lowercase SHA-256 of the
actual dataset artifact, computed by the adapter from its stable serialized
bytes. The example digest is illustrative. Governance records this digest; it
neither stores the artifact nor hashes documentation as a substitute for data.
Adapters must retain the permitted artifact and its serialization specification
and verify its digest when loading data for a run.

Collection boundaries require timezone offsets and are normalized to UTC. Source
references are non-sensitive, stable upstream snapshot/export references, scoped
by the dataset's existing canonical `provider_id`. Do not use mutable "latest"
references. A parent must exist in the same workspace and dataset, precede the
child, and be finalized or archived. Multiple children may branch from a parent.
Cross-dataset processing continues to use the existing transformation/lineage
records. Missing or foreign IDs return 404; invalid parents return 400.

All versions begin in `draft`. Supply all five metadata fields above (other than
optional parent), finish documentation and transformation provenance, then call
`POST /versions/{id}/transitions`:

```json
{ "expected_state": "draft", "state": "finalized" }
```

Only `draft -> finalized -> archived` is allowed. Finalization requires complete
metadata and records a server-generated `finalized_at`. It freezes documentation
history, transformations, and incoming lineage: even direct SQL cannot append
provenance afterward. Corrections require a new version. Archiving records
`archived_at` without altering content, fingerprints, ancestry, or finalization
time. Archived versions remain retrievable but cannot begin production collection;
archive a finalized version to withdraw it without rewriting historical evidence.
Documentation publication and production eligibility remain separate controls.

`GET /versions/{id}` returns exact version metadata, including `created_at` and
lifecycle timestamps. `GET /datasets/{id}/versions` lists all historical versions
in creation order with deterministic ID tie-breaking, pagination, and optional
`state` filtering. Consumers persist the version UUID with their recommendations
and select finalized versions for new runs. They must not resolve a mutable latest
version when reproducing an earlier run. Documentation and transformations remain
available through the existing version-scoped history APIs.

Reads require `governance.view`; creation and transitions require
`governance.manage`. State changes, audit facts and outbox events share a transaction.
Stale/repeated transitions and duplicate version keys return 409. Dataset-row and
version-row locks serialize concurrent creation, finalization and provenance
writes on PostgreSQL; database uniqueness and triggers enforce the same invariants
for direct SQL. SQLite serializes writers and installs equivalent guards.

Legacy rows keep their UUIDs, timestamps, documentation and lineage. Unknown new
metadata remains null and their lifecycle begins at draft, without claiming that
old evidence is reproducible. Create a new complete version to finalize legacy
material; historical rows are never backfilled with fabricated fingerprints.

## Reuse in A&R and future Analytics adapters

`labelos_api.governance` exports strict Pydantic contracts; `GovernanceService`
provides authenticated operations in a caller-owned `AsyncSession` transaction.
It never commits. Callers must commit state, audit and outbox together or roll back
the entire transaction on any error. The HTTP dependency provides this boundary.

Typical adapter sequence:

1. Resolve/register the existing provider, then create a dataset and data version.
2. Append a reviewed datasheet (`expected_revision=0` initially).
3. Create a run pinned to the revision, then transition it to `running` before
   external collection. Commit this transition so failures remain observable.
4. Collect with provider-authorized storage and retention. Record counts and a
   terminal outcome in another transaction. Never send raw provider errors here.
5. Create derived versions after their inputs and record transformation provenance.
   Finalize complete derived versions after recording documentation and provenance.
   Consumers keep exact version/run IDs alongside their own domain objects.

Existing Analytics ingestion is unchanged and remains usable without governance
records. Existing commit-owning Analytics service methods are not an atomic
composition boundary: future adapters must use repository writes or a deliberately
transactional ingestion entry point when atomically linking domain results and
governance completion. This stage does not add A&R workflows, frontend pages,
provider adapters, metric definitions, or backfill unreviewed production approvals.

## Verification

The [Prompt 9 foundation audit](governance-foundation-audit.md) records findings,
fixes, PostgreSQL evidence, and the approval boundary before provider work.
Migration `202610130100` adds governance/provenance lookup indexes. Early
governance downgrades now refuse to discard retained evidence or populated
review/version metadata before changing schema; populated history requires a
forward repair rather than a destructive rollback.

Run `python -m pytest` from `apps/api`. The governance tests cover contracts,
eligibility/revocation, lifecycle, immutable history, tenant FKs, lineage, shared
providers, API authorization, audit/outbox rollback and migration schema parity.
Database behavioral tests also execute on PostgreSQL when `TEST_POSTGRES_URL` is
configured. Without it, PostgreSQL integration is blocked, not verified.
