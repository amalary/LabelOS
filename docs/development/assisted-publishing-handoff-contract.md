# Assisted Publishing Handoff Contract

Assisted destinations are social account connections that expose
`manual_publish` instead of `content_publish`. They are valid planning
destinations, but LabelOS must hand them to a human publishing workflow instead
of an automatic delivery provider.

The [durable Scheduling acceptance boundary](scheduling-delivery-handoff.md) now
defines canonical content snapshots, verified immutable asset copies, receipt
outcomes and fail-closed configuration. It does not enable manual delivery or use
this preparation DTO as acceptance evidence.

## Persistence Decision

Do not create a `manual_publish_tasks` table yet.

The current persistence model already stores the durable content and channel
lifecycle fields that exist today:

- `MarketingContentItem.id`
- `MarketingContentItemChannel.id`
- `MarketingContentItemChannel.social_account_connection_id`
- `MarketingContentItemChannel.scheduled_at`
- `MarketingContentItemChannel.published_at`
- `MarketingContentItemChannel.external_post_id`
- `MarketingContentItemChannel.external_url`

Until there is a Scheduling Engine and Publishing Delivery subsystem with real
assignment, retry, audit, notification, and completion workflows, a separate
manual task table would duplicate lifecycle state prematurely.

## Implemented Contract

`labelos_api.services.marketing_content_service.prepare_assisted_publish_handoff`
returns an immutable `AssistedPublishHandoff` DTO for a single content channel.
It is read-only and has no scheduling, publishing, status transition, or
database-write side effects.

The future Scheduling Engine supplies:

- `ManualPublishScheduleInput.intended_publication_at`

The handoff DTO contains:

- marketing content ID
- channel/content item channel ID
- social account connection ID
- provider
- handle/account display
- `manual_publish` capability
- current connection health status
- asset references
- caption/content, using channel override before item copy
- hashtags only when represented as structured `metadata["hashtags"]`
- scheduler-supplied intended publication timestamp
- safe HTTP(S) profile/provider link
- manual instructions
- optional delivery-owned completion payload

`ManualPublishCompletion` is only a DTO boundary for the future Publishing
Delivery layer. It represents eventual manual result data: completion status,
external post ID, external URL, completion timestamp, and notes.

## Ownership

Social Account Connections provides:

- destination
- capability
- health
- account metadata

Scheduling Engine will provide:

- when

Publishing Delivery will provide:

- execution/manual task lifecycle
- retries for automatic delivery
- publication result/history

## Future Scheduler Consumption

The initial [Scheduling Engine contract](scheduling-engine-contract.md) blocks
manual-only destinations with `manual_delivery_required`. It does not create or
assign manual publishing tasks. `prepare_assisted_publish_handoff` remains a
read-only preparation DTO and is not evidence of durable acceptance.

A future Publishing Delivery manual workflow may consume this DTO with the
content item ID, stable channel ID, and intended publication timestamp. Delivery
owns durable task rows, assignment, reminders, failure history, and final
write-back of `published_at`, `external_post_id`, and `external_url`. Supporting
manual scheduling handoff requires an explicit extension of the Scheduling
acceptance contract; a DTO or no-op receiver cannot mark a job `handed_off`.
