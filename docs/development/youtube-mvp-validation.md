# YouTube A&R MVP — Prompt 5 local validation

Validation date: October 27, 2026 (America/Los_Angeles).

Current checklist follow-up: see [scouting-checklist-closeout-2026-10-27.txt](scouting-checklist-closeout-2026-10-27.txt).
The account, policy and browser blockers described below are historical checkpoints;
use the follow-up for current acceptance evidence. Startup commands below remain valid.

Follow-up after the initial checkpoint: the user completed signup and reached
the authenticated dashboard requests. The first organization request exposed a
`MissingGreenlet` error in `_create_auth_identity`: the new identity stored only
`user_id`, leaving `identity.user` unloaded after the function returned. The fix
assigns the `User` relationship explicitly. A real-session regression reproduced
the original failure before the fix and passed afterward. The API was restarted
with the fix; the user's browser retry and workspace onboarding remain to be
confirmed. The empty-account observations below describe the initial checkpoint.

Follow-up validation: **159 passed / 1 PostgreSQL skip** in the guarded synthetic
run; **3 passed / no skips** on a fresh disposable PostgreSQL cluster, including
the three parallel first-dashboard requests. No development fixtures or account
reset were used. Exact commands:

```powershell
& .\apps\api\.venv\Scripts\python.exe -B apps/api/scripts/youtube_reliability_tests.py tests/test_first_login.py tests/test_auth.py tests/test_onboarding_security.py tests/test_organizations_api.py -q --tb=short --show-capture=no
& .\apps\api\.venv\Scripts\python.exe -B apps/api/scripts/invitation_postgres_tests.py 'C:/Program Files/PostgreSQL/17/bin' tests/test_first_login.py
```

**Decision: stop for approval. The complete live user workflow is BLOCKED, not
certified.** Implementation and automated gates pass. The user has no existing
login; the development database contains no users, workspaces or research runs.
The discovery UI is also disabled with no configured privacy/terms documents.
No production readiness, production migration, policy approval, external account
creation, paid-resource provisioning or Cloud SQL start is claimed.

## Acceptance matrix

| Acceptance criterion                         | Status      | Evidence and limit                                                                                                                                                                                                                               |
| -------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Complete user workflow passes                | **Blocked** | No real WorkOS account/session, workspace, governed session or enabled discovery configuration. Automated route/component flows pass; they are not browser sign-off.                                                                             |
| Normal A&R authorization works               | **Passed**  | Persisted ordinary member, A&R department, `ar.scouting.view/create`; no governance management. SQLite HTTP and disposable PostgreSQL HTTP tests pass. Live account remains blocked.                                                             |
| Saved candidates persist and remain isolated | **Passed**  | Separate HTTP/SQL sessions reopen notes/status; foreign candidate IDs return 404, unauthorized workspaces 403. PostgreSQL HTTP save/edit/reopen verified. Development DB was not seeded with fixtures.                                           |
| No duplicate records are created             | **Passed**  | Sequential saves return the existing ID. Twelve concurrent database saves and twelve concurrent HTTP saves each create exactly one candidate; HTTP gives one 201 and eleven 200 responses. Applies while the source reference exists.            |
| Provider-data lifecycle is correct           | **Passed**  | Automated expiry, unavailable/deleted source, stale display, quota failure, cache deletion and review preservation checks. Expiring source IDs are separate from human records. Operational uptime/backup retention is not production-certified. |
| No secrets exposed                           | **Passed**  | Sanitized provider/proxy failure tests; zero configured WorkOS secret matches in tracked diff and 119 browser JS files. No claim about unrelated logs, external systems or untested live callback logs.                                          |
| Required API/frontend/PostgreSQL tests pass  | **Passed**  | API regression 697 passed / 55 skipped; final focused additions and PostgreSQL results below. Frontend build/type/lint gates pass.                                                                                                               |
| Unverified live API/browser checks reported  | **Passed**  | Every blocked/not-run check is listed below. Live provider adapter checks are explicitly separated from authenticated route/browser checks.                                                                                                      |

## Task matrix

| #   | Requested check                               | Status  | Result                                                                                                                                                                                            |
| --- | --------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Guarded development DB and migrations         | Passed  | Only `127.0.0.1:55432/labelos_ar_dev`, user `labelos`, PostgreSQL 180006. Initially 66 tables at `202610130100`; now 69 at `202610270200`; metadata diff count 0.                                 |
| 2   | Documented local startup                      | Passed  | API on 4000, web on 3000; `/health` and `/health/database` 200, `/login` 200. Corrected conflicting local environment ports.                                                                      |
| 3   | WorkOS authentication and workspace selection | Blocked | Sign-in 307 to WorkOS, hosted form 200, callback points to `http://localhost:3000/api/auth/callback`; credential read-only check 200. No signup/login/callback completion or workspace selection. |
| 4   | Ordinary A&R access                           | Passed  | Automated persisted member authorization and HTTP workflow; real browser account blocked.                                                                                                         |
| 5   | Approved real channel lookup                  | Passed  | One live Google for Developers channel lookup, expected channel ID and expiry. Uses configured Secret Manager reference and shared quota ledger. Diagnostic adapter context only.                 |
| 6   | Bounded keyword search                        | Passed  | One live search, `Google for Developers`, `limit=3`, returned 3. No pagination followed. Automated invalid/oversized requests rejected.                                                           |
| 7   | Facts and YouTube source opening              | Not Run | Current facts/hidden/missing/zero handling and canonical external-link behavior pass component/API tests. No browser surface available: browser inventory empty; no actual YouTube tab opened.    |
| 8   | Save candidate                                | Passed  | HTTP/API and component checks; identifier only, no title/count snapshot. Live browser blocked.                                                                                                    |
| 9   | Reload/reopen                                 | Passed  | New HTTP sessions and component remount reopen persisted review; PostgreSQL verified. Real browser reload blocked.                                                                                |
| 10  | Add/edit notes                                | Passed  | Successive edits persist; revision conflict leaves existing data unchanged and retains unsaved UI text.                                                                                           |
| 11  | Review status                                 | Passed  | `new`, `reviewing`, `shortlisted`, `passed`; invalid and null writes rejected.                                                                                                                    |
| 12  | Filtering/detail                              | Passed  | Status filter, bounded pagination, detail and missing-record responses.                                                                                                                           |
| 13  | Duplicate/concurrent saves                    | Passed  | Unique `(workspace_id, channel_id)` claim, deferred candidate FK, dedicated disposable PostgreSQL; no orphan duplicate candidates.                                                                |
| 14  | Isolation/unauthorized access                 | Passed  | 401 without authentication; 403 missing capabilities/foreign unauthorized workspace; 404 foreign candidate in authorized workspace.                                                               |
| 15  | Stale/missing/deleted/quota-limited data      | Passed  | Provider/viewer regression checks; unavailable channel removes saved source reference while preserving human review.                                                                              |
| 16  | Retention/deletion                            | Passed  | Read suppression and sweep erase expired references; explicit source deletion preserves notes; full candidate deletion removes notes. No provider counters/titles stored.                         |
| 17  | Focused test/build gates                      | Passed  | Commands and results below.                                                                                                                                                                       |
| 18  | Repair MVP defects                            | Passed  | Repairs listed below; live prerequisites remain unresolved.                                                                                                                                       |
| 19  | Exact startup/test instructions               | Passed  | This runbook and tracked guarded launch/check scripts.                                                                                                                                            |

## Repairs made

- Added `/scouting`, active-workspace navigation, a persistent shortlist, detail
  reopening, human labels/notes/status, filtering/pagination and deletion.
- Replaced the research viewer's `governance.manage` requirement with the existing
  scouting capability. A&R users consume prepared governed runs; they cannot
  create/approve governance records through the scouting APIs.
- Added direct channel-ID lookup, source links and save controls to the viewer.
- Added atomic duplicate protection and optimistic revision checking for edits.
- Kept source identifiers in a separate expiring table. No automatic copying of
  provider text or counters into notes. A known unavailable channel erases its
  saved reference. API startup/minute sweeps purge expired references; reads hide
  them even before the sweep. Browser state also removes expired references.
- Prevented fixtures from loading `.env.test.local` or inherited DB/PG settings.
  PostgreSQL opt-in is now an in-process marker set only after a runner verifies
  its newly created cluster's user/database/data directory. The runner constrains
  SQLAlchemy connections to that target or disposable SQLite files.
- Fixed guarded web startup to override stale 3100/4100 settings and pin
  `NODE_ENV=development` for web, `production` for build. The first build failed
  with a nonstandard inherited `NODE_ENV`; the corrected build passed.

Existing dirty/untracked work from prior prompts was preserved. This stage did
not deploy, commit, push, or create external accounts.

## Exact local startup (PowerShell, repository root)

Dependencies must already be installed: Node 22/pnpm 10, the API virtualenv with
editable API/database packages, and the existing local PostgreSQL 18 listener.
No command below starts Cloud SQL or provisions a resource.

```powershell
$python = '.\apps\api\.venv\Scripts\python.exe'
& $python -B scripts/local_database.py status
& $python -B scripts/local_database.py migrate
& $python -B scripts/validate_local_workflow.py schema
```

The launcher reads ignored `.env.labelos-local`, rejects anything except the
pinned local database, removes inherited database/PG variables, and verifies the
database identity with a read-only connection. It then loads root `.env` for
application credentials. Migration uses `-x youtube_quota_approved=true` only
after that target check. Both additive migrations were tested on a fresh cluster
before this development migration. Do not replace this with `pnpm db:migrate`,
an inherited `DATABASE_URL`, recovery copies, or production credentials.

In two terminals, from the repository root:

```powershell
# Terminal 1
& .\apps\api\.venv\Scripts\python.exe -B scripts/local_database.py api
# Terminal 2
& .\apps\api\.venv\Scripts\python.exe -B scripts/local_database.py web
```

Open `http://localhost:3000/login`; the application route is
`http://localhost:3000/scouting`. Stop each launched process with Ctrl+C.
Scheduling and publishing execution are disabled by the guarded profile.
Use `pnpm.cmd` on this Windows host: PowerShell blocks the `pnpm.ps1` shim.

```powershell
& .\apps\api\.venv\Scripts\python.exe -B scripts/validate_local_workflow.py http
```

To finish the live workflow, the user must first create/sign into a WorkOS
account through the existing UI and complete workspace onboarding. A workspace
manager must grant the ordinary A&R member the scouting view/create capabilities
and A&R department access, and prepare a running YouTube collection under the
[existing governance process](youtube-research-api.md#local-use). The local DB is
empty of these records; tests intentionally do not seed it or fake a session.

Discovery additionally needs actual reviewed privacy/terms URLs in root `.env`:

```text
YOUTUBE_RESEARCH_UI_ENABLED=true
YOUTUBE_RESEARCH_PRIVACY_POLICY_URL=https://<actual-reviewed-privacy-document>
YOUTUBE_RESEARCH_TERMS_URL=https://<actual-reviewed-terms-document>
```

These are configuration placeholders, not approved documents. Restart web after
configuration. Existing Secret Manager configuration is sufficient for the live
adapter smoke check; no secret value is copied into source code or the browser.

## Test commands and observed results

All fixtures below are synthetic. The recovered development database is never a
test target. Default Pytest now disables PostgreSQL regardless of saved or
inherited URLs. The synthetic wrapper additionally blocks `asyncpg.connect`.

```powershell
& .\apps\api\.venv\Scripts\python.exe -B apps/api/scripts/youtube_reliability_tests.py tests/test_scouting.py tests/test_youtube_reliability.py tests/test_youtube_research_api.py tests/test_public_music_adapters.py tests/test_research_providers.py tests/test_governance.py tests/test_governance_authorization.py tests/test_governance_audit.py tests/test_collection_runs.py tests/test_analytics_service.py tests/test_auth.py tests/test_authorization_service.py tests/test_authorization_guards.py tests/test_authorization_permission_matrix.py tests/test_onboarding_security.py tests/test_invitation_security.py tests/test_scheduling_processor_migration.py tests/test_scheduling_persistence.py tests/test_publishing_persistence.py -q --tb=short --show-capture=no --junitxml=../../test-results/prompt5-api.xml
```

Observed broad regression: **697 passed, 55 skipped, 158.01 seconds**. Skips are
PostgreSQL-specific tests in the synthetic-only run and unsupported provider
combinations. Later added focused scouting checks passed **5 / 3 skipped** in
SQLite; all 3 PostgreSQL checks ran successfully in the dedicated runner below.

```powershell
& .\apps\api\.venv\Scripts\python.exe -B apps/api/scripts/invitation_postgres_tests.py 'C:/Program Files/PostgreSQL/17/bin' tests/test_scouting.py tests/test_youtube_reliability.py --junitxml=../../test-results/prompt5-postgres.xml
```

Observed: **25 passed, 15.48 seconds, no skips**. The reused runner's historical
name is `invitation_postgres_tests.py`; arguments select the scouting suite. It
initializes a new temporary local cluster, chooses a free loopback port, verifies
its directory/user/database, runs tests with per-test schemas, then stops/removes
only its own cluster. Full migration-chain upgrades, 12-way database and HTTP
deduplication, and 90-way quota contention are included. PostgreSQL 17 binaries
were available; development PostgreSQL 18 identity/schema/health were checked
separately. Initial sandbox `initdb` failed before creating a server; the runner
then succeeded with host execution. No saved database target was substituted.

```powershell
pnpm.cmd --filter @label-os/web exec vitest run src/components/scouting-workspace.test.tsx src/components/youtube-research-panel.test.tsx src/app/api/workspaces/scouting-proxy.test.ts src/app/api/workspaces/youtube-research-proxy.test.ts src/lib/workspace-navigation.test.ts src/lib/api-client.test.ts src/lib/redirects.test.ts src/app/api/auth src/app/onboarding/workspace/actions.test.ts src/app/join
pnpm.cmd --filter @label-os/web typecheck
```

The frontend suite covers AuthKit/proxy/onboarding regressions and scouting
remount/edit/filter/conflict/source-link behavior with mocked HTTP. These are
component tests, not real browser tests. Final result: **68 passed across 11 files,
9.38 seconds**. Typecheck passed.

Stop the dev web process before building (both use `.next`):

```powershell
& .\apps\api\.venv\Scripts\python.exe -B scripts/local_database.py build
& .\apps\api\.venv\Scripts\python.exe -B scripts/validate_local_workflow.py secrets
```

Build **passed**, including Next lint/type validation and 23 generated pages.
The initial compilation emitted WorkOS Edge-runtime API warnings; no dependency
upgrade or production compatibility claim is made. Secret scan: **0 matches in
tracked diff and 119 browser JavaScript files**. It does not inspect unrelated
system logs or untested callback logs.

Live checks are separate from tests and spend actual bounded provider quota:

```powershell
& .\apps\api\.venv\Scripts\python.exe -B scripts/validate_local_workflow.py youtube
```

Observed: lookup **passed**; three-result search **passed**. No cursor followed,
no provider content saved, no workspace/run authorization fabricated. Only the
content-free quota ledger is updated. This does not verify the authenticated
scouting request against an actual governed workspace.

## Retention and remaining gates

Human reviews live in `scouting_candidates`. `scouting_sources` stores only the
channel reference, candidate/workspace IDs and expiry. The 29-day window leaves
one day of margin relative to the existing 30-day upper-bound design. Duplicate
saves do not refresh expiry. After deletion/expiry no identifier or hash is kept
for matching a later new save; human notes remain unless explicitly deleted.
No channel names, statistics, raw responses, queries or derived scores are stored
in these tables. Existing volatile cache/browser display limits remain in force.

The minute sweep requires the API to run. Expired references are hidden from all
API reads even after downtime; deployment uptime, independent cleanup scheduling,
backup expiry/restore sanitation, external deletion processes and legal approval
remain production gates. No production data or backups were inspected.

Browser inventory returned no available browser, and the user confirmed they
have never made a login. WorkOS session creation, workspace selection, an ordinary
member's actual browser access, the integrated live discovery/save/reload/review
flow, and opening YouTube in a browser remain **unverified**. Do not remove these
gates based on passing mocked or adapter-only tests.

Approval requested next: review the MVP repairs and authorize a separate guided
first-account/workspace setup and remaining live walkthrough. This report does
not authorize deployment or imply production readiness.

## Final closeout

- Final frontend build: exit 0; 23 pages generated. Scoped ESLint, Ruff and
  `git diff --check` passed. The final deleted-reference test is included in the
  68-test frontend result above.
- The documented HTTP checker was rerun successfully: health/database 200,
  `/api/v1/me` 401, login page 200, sign-in and `/scouting` 307 to WorkOS with the
  localhost:3000 callback; hosted form 200.
- API and web processes started for validation were stopped after these checks.
  The pre-existing development PostgreSQL listener is unchanged. Disposable test
  clusters were stopped and removed by their runner.
- No unresolved automated test failures. Remaining blockers are the actual
  account/workspace/governed-session setup, reviewed discovery configuration and
  a real browser walkthrough. Do not infer that the complete workflow passed.
