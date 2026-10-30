# Public YouTube research API

Reliability and retention decisions, deployment prerequisites and the guarded
test command are documented in [the Prompt 4 review](youtube-reliability-policy.md).
The quota and shortlist migrations were applied to the guarded local development
target during [Prompt 5 validation](youtube-mvp-validation.md). Other targets are
not approved by that check. Use the guarded launcher, not inherited database URLs.

The application now registers authenticated research routes under
`/api/v1/workspaces/{workspace_id}/research/youtube/runs/{run_id}`:

| POST route      | JSON body                                      | Result                                                               |
| --------------- | ---------------------------------------------- | -------------------------------------------------------------------- |
| `/search`       | `{"query":"Google for Developers","limit":10}` | Public channel candidates; optional `cursor` continues a page        |
| `/lookup`       | `{"channel_id":"UC…"}`                         | One public channel                                                   |
| `/observations` | `{"channel_id":"UC…"}`                         | Current public views, subscriber count when visible, and video count |
| `/channel`      | `{"channel_id":"UC…"}`                         | Metadata and current counters from one upstream call                 |

`DELETE /display-cache` clears this workspace's volatile display data. Other
replicas expire their entries within 60 seconds. It does not delete YouTube data.

Requests require normal WorkOS bearer authentication and `ar.scouting.view`
capability with A&R department access in the selected workspace. Preparing or
changing governance records still requires `governance.manage`.
An active collection run must belong to
that workspace and the registered `youtube` source. The server derives provider,
run and version IDs from the database. Clients cannot submit a secret, credential
reference, provider ID, context, or upstream URL.

The response uses the existing normalized contracts and includes provenance and
expiry. It carries `Cache-Control: no-store`. No raw responses, analytics rows,
derived scores, historical series or cross-owner aggregates are stored. These
routes do not automatically checkpoint or complete runs: the collection owner
uses the existing governance lifecycle and must not claim records were written
merely because a display request returned data.

## Credential configuration

Use `CREDENTIAL_STORE_BACKEND=gcp-secret-manager` and
`CREDENTIAL_STORE_GCP_PROJECT_ID=<project>`. Store a JSON credential payload with
an `api_key` field using the existing `CredentialStore`.

`YOUTUBE_RESEARCH_CREDENTIALS` is a JSON object mapping workspace UUIDs to
`gcp-secret-manager://projects/<project>/secrets/<secret>` references. References
must belong to the configured project. Missing workspace entries fail closed.
The server identity needs access to the selected secret.

For a local checkout only, `YOUTUBE_RESEARCH_LOCAL_CREDENTIAL_REF` can name one
shared development credential. This allows newly onboarded local workspaces to
use the key after authorization; explicit workspace entries take precedence.
Startup rejects this fallback in production-like environments. Clear it and set
the explicit workspace map before deployment. No secret value is stored in `.env`.

## Local use

1. Follow the pinned database, migration and startup commands in
   [the local validation runbook](youtube-mvp-validation.md).
2. Start the API and web with `scripts/local_database.py api` and `web` using
   the API virtual environment. This overrides conflicting inherited DB/port values.
3. Sign in and create/select a workspace using the normal LabelOS onboarding.
   An empty local database does not contain a pre-authorized user or workspace.
4. Through `/api/v1/workspaces/{workspace_id}/governance`, register a source with
   `key: "youtube"`, create its dataset and version, and document that version.
   Local exploration can use draft documentation with `production_eligible: false`;
   do not invent a license approval or completed review.
5. Create a collection run referencing that documentation with `production: false`
   and a unique `run_key`, then transition it to `running`.
6. Call the research routes with its ID. Finish the run through the existing
   governance transition endpoint when the display session is over.

### Local setup from the scouting page

With the guarded local launcher (`APP_ENV=local`), a member with
`governance.manage` can click **Prepare local YouTube session** on `/scouting`.
This calls `POST /api/v1/workspaces/{workspace_id}/scouting/local-session` and
uses the existing governance service to register the source, create a dataset,
draft version/documentation, and start a non-production run in one transaction.
It reuses an active non-production YouTube run; concurrent setup is serialized
by workspace. It makes no provider request and changes no memberships or grants.
The API returns 404 outside development/test and 403 without governance access.
Ordinary scouts still only need scouting access to use a prepared run.

The bundled `/privacy` and `/terms` pages are local research drafts. Configure
`LABELOS_POLICY_OPERATOR` and `LABELOS_PRIVACY_CONTACT` with real details. After
the operator reviews the documents and confirms the described deletion and
retention practices, local discovery can use them with:

```text
APP_ENV=local
YOUTUBE_RESEARCH_UI_ENABLED=true
YOUTUBE_RESEARCH_USE_LOCAL_POLICIES=true
LABELOS_RESEARCH_POLICIES_APPROVED=true
```

Restart the guarded web launcher after changing root environment configuration.
Missing operator/contact/approval keeps bundled documents from enabling research.
Public deployments still require actual HTTPS policy URLs and their own review;
the local setup action and relative-policy exception are unavailable there.

For manual browser acceptance, sign in, open `/scouting`, prepare a session as a
governance manager, then use a separately authorized ordinary A&R member to:
agree to the reviewed policies, search explicitly, look up a channel, save it,
add a human label/notes/status, reload, and reopen it. Verify workspace switching
does not expose the other workspace's review. Keep test notes clearly identified.
Automated component tests and local owner access do not certify this member flow.

For new members, an owner can choose **A&R** in the invitation dialog. This grants
the `a_and_r` role and `a&r` department access, without `governance.manage`.
For an existing member, open `/workspace/settings`, find **Member Roles**, select
the member's **A&R** role and **A&R department access**, then **Save roles**.
Department changes are explicit, owner-only, audited, and saved atomically with
the selected roles. Other department grants are preserved by the form. Role-only
API requests preserve department access. Refresh the member's browser afterward.
Invitation links must be shared manually; creating a link does not send email.

The local API reference at `http://127.0.0.1:4000/docs` lists all request schemas.
Production deployments require production runs and currently eligible, latest
documentation on every request. Archived versions and terminal runs are rejected.
Run/version locks prevent concurrent lifecycle changes while a request executes.

## Shortlist

`/scouting` uses the active workspace and discovers running governed sessions.
The API prefix is `/api/v1/workspaces/{workspace_id}/scouting`:

- `GET /runs`: bounded running YouTube session list.
- `GET /candidates?status=shortlisted&limit=50&offset=0`: filtered, paginated review list.
- `POST /candidates` with only `channel_id`: 201 for a new save, 200 for an existing save.
- `GET /candidates/{id}`: reopen a workspace-scoped review.
- `PATCH /candidates/{id}`: human `label`, `notes`, `status` and required current `revision`.
  A stale revision returns 409 without overwriting another review.
- `DELETE /candidates/{id}/source`: erase the saved YouTube reference; preserve human review.
- `DELETE /candidates/{id}`: delete the candidate, source and human notes.

Reads require `ar.scouting.view`; writes require `ar.scouting.create`. Both use
persisted workspace authority and department access, without granting governance
management. Human review fields are separate from the source table. The source
reference expires after 29 days and is erased by the API's minute sweep; reads
hide expired references immediately. Duplicate saves do not extend expiry or
overwrite review. Provider titles/counters are never copied into review fields.
After a reference is deleted or expires, the system deliberately has no retained
channel identifier/hash to match a later new save against that old human review.

## Failures and validation

Missing authentication returns 401; insufficient permission 403; missing or
foreign run 404; ineligible run 409; invalid request 422; quota/rate limits 429;
unavailable credentials or provider 503; upstream timeout 504. Provider failures
return only an allowlisted `detail.code`, with `Retry-After` where supplied.
Searches are not retried automatically. Channel reads have at most two attempts
for transient failures, with bounded backoff and a shared quota reservation for
each attempt. Rate limits, quota failures, missing channels and authentication
failures are not automatically retried.

Tests: `python -m pytest tests/test_youtube_research_api.py
tests/test_public_music_adapters.py tests/test_research_providers.py
tests/test_governance_api.py -q`. The default tests use synthetic data and do not
need real credentials or consume quota.
