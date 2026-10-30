# Phase 3 A&R — Prompt 9: Governance foundation audit

Audit date: 2026-10-13. Baseline: `9764e3c`. Scope: the repository's implementation
and documentation of Prompts 2–8, before live provider integration. This review
covers contracts, services, HTTP routes, database models and guards, migrations,
authorization, audit/outbox composition, and their tests. No provider adapter,
credential connection, external collection, or production deployment was added.

## Decision

**Ready for Prompt 10 development after approval.** The three findings below are
fixed, and the final combined verification passed **345 tests with no failures or
skips**, including real PostgreSQL integration and concurrency tests. Within the
documented service/database trust boundary, the foundation is production-compatible
for the next stage. Live activation still depends on the adapter controls and
release validation listed under residual risks. This audit has not deployed the
new migration or enabled provider access.

## Findings and fixes

| ID    | Priority | Finding                                                                                                                                                                                                                                                             | Resolution                                                                                                                                                                                                                                                                                                                                                          |
| ----- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G9-01 | High     | Downgrades `202610120100`, `202610120200`, and `202610120300` could discard immutable governance evidence, documentation review state, or version fingerprints/lifecycle metadata. The later collection/provenance migrations already refused comparable data loss. | Added read-only preflight checks before any grants, guards, columns, or tables change. Foundation downgrade refuses any governance history; documentation downgrade refuses reviewed or non-self-authored history; version downgrade refuses populated version metadata or lifecycle history. Empty and legacy-compatible rollback remains supported.               |
| G9-02 | Medium   | Source registration used a read-then-insert sequence. Simultaneous first registrations of the same canonical workspace/key could yield an integrity failure instead of reusing the source.                                                                          | Registration now uses the existing registry's unique constraint with `ON CONFLICT DO NOTHING … RETURNING`. The losing request loads and compares the winner: equal attributes reuse its ID; incompatible attributes raise a governance conflict. Only the creator appends registration activity and an outbox event. No internal commit is introduced.              |
| G9-03 | Medium   | Several governance/provenance foreign-key and history lookups had no supporting index. This would add scans as collection and lineage history grow.                                                                                                                 | Added nine indexes in additive migration `202610130100`, with matching ORM metadata. They cover dataset/provider ownership, workspace version history, run/documentation, transformation/run, activity/entity history, provenance record/version and record/run, provenance transformation/run, and workspace record history. Downgrade removes only these indexes. |

The historical migrations' **upgrade definitions and revision IDs are unchanged**.
Their downgrade safety checks must ship with the application because these checks
execute from migration code, including against databases already at the old head.
The index addition has its own forward migration; it does not rewrite evidence.

Regression tests were added in `apps/api/tests/test_governance_audit.py`. Existing
migration head/parity assertions were updated. The first concurrency-fix attempt
exposed SQLite legacy savepoint behavior in the existing rollback test; the final
conflict-safe insert preserves the caller's transaction on both supported test
dialects. No unresolved failure from that attempt remains in the final result.

## Audit coverage

| Requested area                                  | Assessment and evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Schema, indexes, FKs, uniqueness, migrations | Workspace-composite FKs scope datasets, documentation, runs, transformations, and graph edges. Workspace source/dataset keys, dataset version keys, documentation revisions, run keys, retry predecessors, producing transformations, and graph edges have uniqueness enforcement. SQL triggers supplement FKs for immutable ancestry and lifecycle rules. New indexes address G9-03. Metadata parity and migration round trips cover SQLite and PostgreSQL.                                                                                          |
| 2. Source registry and dataset documentation    | `analytics_providers` remains canonical; there is no duplicate provider or metric registry. Datasheet contracts cover provenance, collection, ownership, licensing, privacy, retention, schema fields, limitations, and review lifecycle. Drafts can be incomplete; validation/publication require complete documentation. Corrections append a fresh draft and require fresh review. Terms-sensitive production eligibility is rechecked at run creation and start.                                                                                  |
| 3. Version immutability and collection tracking | Version identity, fingerprints, metadata, and parentage are immutable from creation. Only draft → finalized → archived is allowed; finalization freezes appended documentation and provenance. Runs pin an exact documentation revision and expose the corresponding source/version. Bounded retries, retry uniqueness, due times, monotonic counts, optimistic checkpoint revisions, and immutable terminal results are enforced. Archive blocks new production collection.                                                                          |
| 4. Transformation lineage                       | Dataset lineage enforces input-before-output ordering. Record provenance uses immutable increasing generations, scoped edges, transformation version/actor facts, and historical artist/observation bindings. Service transformations validate all inputs before atomic writes. Graph traversal is bounded and reports truncation or corrupt/missing ancestry. Artist and observation IDs intentionally use insertion-time ownership checks rather than cascading FKs so canonical deletion cannot erase history.                                     |
| 5. Authorization and workspace isolation        | Reads require persisted `governance.view`; mutations require persisted `governance.manage`. Source details require the additional manage grant. All routes use the shared authorization service and workspace-scoped loads. Tests cover removed memberships, forged claims/role names, unrelated A&R/Analytics grants, custom grants, foreign nested IDs, and generic-model read rejection. Database FKs prevent cross-workspace provenance links.                                                                                                    |
| 6. Idempotency and concurrency                  | Source registration now passes simultaneous equal/conflicting requests. Run creation and terminal replay retain stable identity/outcomes; conflicting requests fail. PostgreSQL tests cover concurrent documentation revisions, version keys/finalization, direct SQL provenance insertion versus finalization, run transitions/completion, retries, and checkpoint compare-and-swap. Record transformations intentionally create new events; delivery deduplication remains the adapter's responsibility.                                            |
| 7. Audit and sensitive information              | Each authorized service mutation writes durable actor/action/entity activity and an identifier-only realtime outbox event in the same caller-owned transaction. Rollback tests verify all-or-nothing behavior. Documentation and provenance are append-only. Provider metadata/credential relationships are excluded from governance projections; source account IDs, raw locators, and raw content hashes have explicit redaction rules. Error categories and checkpoint fields are allowlisted, and validation errors do not echo submitted values. |
| 8. Existing Analytics compatibility             | Existing providers and metric definitions remain authoritative. Existing Analytics ingestion and APIs remain usable without invented governance evidence. Realtime uses the existing outbox. Compatibility tests exercise Analytics, central authorization, realtime, and scheduling/publishing migration checks. Commit-owning Analytics service calls are not an atomic composition boundary for future governed ingestion.                                                                                                                         |
| 9. Upgrade/downgrade behavior                   | The single migration chain now ends at `202610130100`. Tests cover the complete PostgreSQL upgrade chain followed by actual governance operations, schema parity, populated legacy upgrades, additive index downgrade/re-upgrade, history-preserving rollback refusals, and guards still rejecting edits after a refused rollback. Tests invoke revision operations; deployment environment/CLI configuration is not certified by these tests.                                                                                                        |
| 10. Unit and PostgreSQL coverage                | Existing contract, API, lifecycle, authorization, rollback, and database guard cases were retained. New tests add source registration races, checkpoint competition, populated index round trips, protective downgrade refusal, and governance behavior on a fully migrated PostgreSQL schema. PostgreSQL was available and exercised, not skipped. Final counts and measured coverage appear below.                                                                                                                                                  |

`parent_version_id` is protected by an insertion guard checking workspace, dataset,
parent lifecycle, and time order; immutable versions cannot subsequently be
deleted. External `job_id`, `source_reference`, and `cursor_reference` values are
opaque references, not local-resource authorization grants.

## Test evidence

Environment: Windows, Python 3.14.0, SQLAlchemy 2.0.49, PostgreSQL 17.5. SQLite
behavioral tests ran alongside PostgreSQL. Each PostgreSQL fixture uses a separate
temporary schema. Repository CI configures Python 3.12 and PostgreSQL 16; that CI
matrix was inspected but was not executed by this local audit.

- Baseline governance suite: **116 passed**.
- Intermediate Analytics and migration compatibility suite: **76 passed**.
- Final combined verification: **345 passed, 0 failed, 0 errors, 0 skipped**, in
  **251.52 seconds**. This includes 36 PostgreSQL-labeled cases plus PostgreSQL
  fixtures used by the source-registration races and publishing migration test.
- Coverage across the five selected governance modules: **723/753 statements
  (96.02%)** and **194/226 branches (85.84%)**; pytest-cov's combined display is
  **94%**. The governance HTTP route module has 100% line and branch coverage;
  record-provenance service coverage is lower (88.99% lines, 75% branches).
  Remaining gaps include defensive invalid-input/reference and traversal-budget
  branches. Database guards and unrelated modules are outside this coverage
  denominator, though exercised by integration tests.
- API Ruff lint and the new migration's Ruff check: **passed**.
- `git diff --check`: **passed**. Markdown formatting: **passed**.

The final combined command, run from `apps/api`, is:

```powershell
python -m pytest tests/test_governance_audit.py tests/test_governance.py tests/test_dataset_documentation.py tests/test_dataset_versioning.py tests/test_collection_runs.py tests/test_transformation_lineage.py tests/test_governance_authorization.py tests/test_governance_api.py tests/test_analytics_service.py tests/test_analytics_api.py tests/test_authorization_service.py tests/test_authorization_permission_matrix.py tests/test_authorization_guards.py tests/test_realtime.py tests/test_publishing_persistence.py::test_migration_round_trip tests/test_scheduling_persistence.py::test_full_migration_upgrade_downgrade_reupgrade tests/test_scheduling_processor_migration.py -q --junitxml=../../test-results/governance-audit.xml --cov=labelos_api.governance --cov=labelos_api.provenance --cov=labelos_api.services.governance_service --cov=labelos_api.services.provenance_service --cov=labelos_api.api.v1.governance --cov-report=term-missing --cov-report=xml:../../test-results/governance-audit-coverage.xml
python -m ruff check .
```

JUnit and coverage XML are local, ignored artifacts under `test-results/`. This
was a focused foundation and compatibility verification, not a whole-repository
test run, frontend review, load test, or live-provider test.

## Residual risks and Prompt 10 requirements

1. **Adapter transaction and delivery semantics.** Record-level registration and
   transformations do not deduplicate matching inputs. The adapter must persist
   delivery identity and data writes with provenance and checkpoint/completion in
   one transaction. Use repository writes or a deliberately transactional entry
   point; existing Analytics methods that commit internally cannot provide this
   guarantee. Commit a run's start before external work, then record the outcome.
2. **No external enforcement yet.** Retention, credential access, provider terms,
   raw storage deletion, rate limiting, external cursor resolution, and recovery
   of abandoned running jobs need implementation and failure tests in the adapter
   stage. Documentation approval alone does not implement those controls. Terms
   revocation does not stop an already running external collector.
3. **Trust boundary.** Workspace isolation is enforced by authenticated service
   queries plus composite ownership constraints, not tenant database RLS. SQL
   writers and database administrators are trusted; direct SQL is not a substitute
   for service authorization, datasheet validation, eligibility checks, or audit
   emission. The triggers protect specific integrity/immutability invariants;
   they do not validate every API contract or protect against disabled triggers.
4. **Sensitive prose and artifacts.** Free-text documentation, source references,
   and code references must remain non-sensitive; the contracts are not a secret
   scanner. Do not store raw payloads, credentials, signed URLs, or personal data
   in immutable prose. Source-store permissions and digest verification still
   apply when resolving opaque references. Actual data fingerprints are supplied
   by the adapter, not computed or independently verified by governance.
5. **Version and review policy.** Publication and production eligibility are
   intentionally separate for compatibility. Eligible drafts can collect; only
   complete versions can finalize, and missing immutable metadata cannot be
   patched into an old draft. Consumers must pin exact finalized version IDs;
   adapters must explicitly construct complete output versions and lineage when
   producing reproducible artifacts. Do not silently substitute a latest version.
6. **Deployment and scale.** The nine index builds use ordinary transactional DDL
   and may block writes on populated tables. Schedule deployment accordingly and
   assess production table sizes. Load, query-plan, disaster-recovery, and the
   CI Python/PostgreSQL version matrix remain release verification tasks. Retained
   history intentionally blocks destructive downgrades; use a forward repair or
   an explicitly planned backup/restore procedure instead of bypassing the checks.

## Approval boundary

Stop after this audit and its in-scope fixes. Prompt 10 implementation and live
provider access require the user's next approval; neither has been initiated.
