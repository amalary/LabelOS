# Prepared media for scheduled publishing

Save a draft, then use **Upload shared media** or a channel's **Upload media**
control. Save the draft again to attach the returned reference, submit it for
approval, and activate the channel schedule. YouTube requires one video for that
target. A channel's nonempty media list overrides the shared media list.

The authenticated API accepts raw bytes at
`POST /api/v1/workspaces/{workspace_id}/marketing-content/{content_item_id}/assets`
with an `image/*`, `video/*` or `audio/*` Content-Type. The caller needs
`marketing.content.edit` in the workspace and campaign. The response contains
`sha256`, `size_bytes`, and `media_type`; attaching it uses the existing draft edit
API. Uploading alone does not change the draft, its revision, or its approval.
Attaching or replacing references invalidates approval through the normal edit
transaction. The web proxy uses server-side authentication and bounded buffering.

Media lives in `marketing_media_assets`, scoped by workspace, content item and
SHA-256. Identical uploads are idempotent. Existing bytes cannot be overwritten
through this API. A digest from another workspace or content item grants no access.
Scheduling uses its existing locked source transaction to resolve approved media,
check MIME type, length and digest, then create the immutable publication envelope.
No caller-injected byte mapping or external URL fetch is needed in production.
The separate Publishing worker delivers those snapshotted bytes with the real
YouTube adapter. Uploads never call a provider or activate a schedule.

Limits remain **16 MiB per asset** and **24 MiB for the serialized handoff payload**,
including base64 expansion and copy. Resolution accepts at most 32 references and
bounds the aggregate byte count before reading blobs. Oversized, missing,
cross-content, or corrupt media fails closed as `handoff_contract_violation`, with
no accepted Publication or provider call. Existing arbitrary JSON IDs/URLs are not
automatically converted: upload the original file, replace the reference, save,
and obtain approval again.

## Rollout and storage

Apply Alembic revision `202609210100` (`alembic upgrade head`) before deploying the
new API and Scheduling worker. Grant the API role SELECT/INSERT and the Scheduling
role SELECT on the new table if deployment uses explicit table-level grants.
Publishing keeps using its immutable envelope and needs no media-table access.
No new external storage service, credential, or environment variable is required.
Keep both workers' existing execution controls and workload identities in place.

This implementation uses PostgreSQL bytea for bounded files. Plan database disk,
backup and memory capacity accordingly. Uploaded but unattached media remains
with the draft; there is no garbage collector in this change. Deleting a content
item cascades its source uploads, subject to existing content deletion constraints.
Accepted publications retain their own immutable copy. Larger files and storage
lifecycle management need a separate object-storage/resumable-upload design.

Downgrading this revision deletes uploaded source media, so preserve a backup and
disable Scheduling first; restoring the migration alone does not restore files.

## Verification

`test_marketing_media.py` covers permission checks, tenant/content isolation,
idempotency, bounded uploads, digest/metadata validation and channel overrides on
SQLite and PostgreSQL. `test_production_media_postgres.py` exercises draft creation,
upload, edit, approval, activation, the workload-authenticated Scheduling endpoint,
and the separate production Publishing worker with its real provider registry and
YouTube adapter. Only Google HTTP and external credential storage are substituted.
It verifies exact outgoing bytes, published evidence, history, realtime events,
and replay without a second upload for both shared and channel-specific media.
Live Google credentials and a live YouTube upload are not part of these tests.
