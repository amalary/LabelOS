# Scheduling in the Marketing Hub

Channel authoring stays on `MarketingContentItemChannel` in the existing Calendar
and Draft Posts editor. Parent `scheduled` status is displayed as **Planned**;
it does not activate delivery. The old parent status-only Schedule action has
been replaced by channel-level **Activate Schedule**.

1. Configure channel copy/assets, compatible destination, local time and IANA
   timezone. Repeated DST times require an explicit earlier/later occurrence;
   nonexistent times cannot be saved.
2. Save and submit the current revision through the existing approval workflow.
   Unsaved changes disable submission and activation.
3. Complete review in Approvals, then reopen the content.
4. Activate each approved channel independently. The API validates both content
   revision and schedule generation and requires `marketing.content.schedule`.
5. Inspect pending, claimed, blocked, cancelled, superseded, or handed-off jobs.
   Inspection refreshes every 15 seconds and can also be refreshed manually.
   Older jobs use the API's cursor pagination.
6. Cancel pending, claimed, or blocked work. A concurrent durable handoff can
   win; the UI displays the conflict and refreshes the job's actual state.
7. To reschedule, cancel mutable work, edit and save the channel intent, complete
   fresh approval, then activate a replacement. History retains the predecessor
   link. Revalidation only retries unchanged approved blocked intent. Cancelled
   intent may also be explicitly replaced using still-current approval, as the
   API allows.

**Publish Now** prepares a local channel time from the current instant. It does
not submit, approve, activate, or publish implicitly. The user must save, obtain
approval, and activate. If approval takes longer than the delivery window, the
API requires a material time edit and fresh approval.

Handed off means durable delivery acceptance, never confirmed publication.
Only a channel's recorded `published_at` is displayed as published. Manual
destinations require a separate delivery workflow. Disabled execution or an
unconfigured receiver is explained and prevents activation; viewing history and
cancelling mutable jobs remain available even with authoring disabled.

The web routes forward through the authenticated workspace proxy. POSTs carry
UUID idempotency keys; the UI retains the key for a retry after an uncertain
network/server outcome. Server conflict reason codes are mapped to recovery
instructions. No endpoint mutates job timestamps or bypasses approval.

Validation lives in `channel-scheduling.test.tsx`, `marketing-workspace.test.tsx`,
`scheduling-proxy.test.ts`, and the existing timezone tests. The Marketing Hub
integration test exercises authoring through approval, activation, cancellation,
material editing, second approval, and replacement, using the real scheduling
HTTP client and simulated content/approval responses.
