# Scheduling to Publishing production composition

`DELIVERY_RECEIVER_BACKEND=publishing` connects the private Scheduling worker to
Publishing's existing transactional receiver. `unavailable` remains the default
and returns a refusal before claims. No new queue, HTTP execution endpoint,
scheduling policy, provider policy or schema is introduced.

The path is: approved channel schedule → Scheduling activation and due claim →
Scheduling handoff composer → workspace-scoped PublishingDeliveryReceiver →
durable pending Publication → separate Publishing worker → configured provider
adapter. The orchestrator's explicit `accept_execution` uses the same receiver.

## Deployment

1. Apply all existing database migrations, including Publication lease/recovery
   storage, to the shared PostgreSQL database at READ COMMITTED. Intake requires
   asyncpg and `DATABASE_ECHO=false`; invalid configurations fail startup.
2. Set `DELIVERY_RECEIVER_BACKEND=publishing` on the human API (readiness/activation)
   and private Scheduling worker. Enable `SCHEDULING_EXECUTION_ENABLED` and the
   workspace's durable Scheduling execution control when ready. Retain the
   existing dedicated Google OIDC invoker and deployment-scoped workspace.
3. Configure the separate Publishing job against that same database and workspace:
   `PUBLISHING_WORKER_WORKSPACE_ID=<workspace>`, `PUBLISHING_EXECUTION_ENABLED=true`.
   Invoke `python -m labelos_api.publishing_worker --execute` on the deployment's
   chosen recurring cadence. Its runtime identity needs DB access and the existing
   production credential-store/OAuth configuration. The Scheduling worker needs
   transactional DB intake access, not provider credentials or provider API access.
4. Keep worker credentials and invocation authority separate from human API roles.
   The Scheduling endpoint authenticates workload OIDC; Publishing remains a
   private process/job with deployment/IAM authority and no public execution route.

Both environment templates retain disabled execution defaults. Selecting intake
does not start or enable the Publishing job. A Publishing process outage safely
leaves committed work pending; no worker liveness probe is required for durable
acceptance. Monitor pending Publications and each worker's fixed outcome counts.
Existing provider capability and payload rules still apply: only YouTube has a
production adapter. Content uploads now persist prepared media in PostgreSQL;
Scheduling loads the approved, content-scoped bytes before building its immutable
payload. See [prepared media](prepared-media.md) for authoring, limits and rollout.

## Transactions, failure and replay

Scheduling commits its fenced claim first. Its existing handoff savepoint then
encloses Publication creation, Publication lease/outbox, the fenced `handed_off`
transition, receipt, and Scheduling history/outbox. The caller commits once.
Source/job/destination locking, full envelope comparison and existing unique
workspace/job and workspace/channel/revision/generation constraints prevent
duplicate Publications. Exact replay returns the original receipt; conflicting
payloads fail closed. The receiver cannot change its host-supplied workspace.

Missing Publishing tables, permissions or failed writes cannot leave a successful
handoff or partial Publication. Unknown errors retain the leased Scheduling claim
and report `job_failed`; they are not guessed to be safe retries. After expiry,
the existing recovery pass reclaims unaccepted work within the lateness policy.
If the handoff committed but its acknowledgement was lost, replay observes the
original `handed_off` job and Publication without creating another. Known explicit
nonacceptance retains the existing bounded Scheduling retry policy.

Publishing discovers only committed Publications. It commits its own fenced
claim and attempt before adapter I/O, then commits evidence/outbox and lease
release separately. An interrupted started attempt follows existing conservative
recovery and reconciliation; it is never blindly republished. Exactly-once remote
provider execution is not promised.

Cancellation/supersession before handoff remains Scheduling-owned. Once handed
off, cancellation of waiting work uses Publishing's existing cancellation path.
Source approval/revision/generation/intent changes are rechecked before execution.
The existing rejection of Scheduling cancellation after handoff is unchanged;
this change does not add coordinated postacceptance cancellation.

## Verification

`test_scheduling_publishing_composition_postgres.py` activates real future channel
schedules using API-derived controls, invokes the production OIDC Scheduling app
with its real configured receiver, and executes the separate Publishing worker.
Only external provider/credential infrastructure is substituted. PostgreSQL cases
cover duplicate/concurrent handoff, conflicting replay, cancellation/supersession,
workspace isolation, missing lease storage after Publication insertion, rollback,
lost commit acknowledgement, and restart with one Publication and one provider call.
Existing Scheduling, Delivery, Publishing worker, provider and recovery suites
remain the subsystem regression coverage.

Closeout validation on 2026-09-17 used isolated schemas on local PostgreSQL 17:
1,173 tests passed across the 30 Scheduling/Publishing/Delivery/recovery suites.
The final focused handoff and composition run passed 56 tests, including the
added human-token refusal and hostile request-body workspace override checks.
API-wide Ruff, root Pyright, changed-file Black/Prettier and `git diff --check`
passed. Provider execution in composition tests uses a deterministic test adapter;
deployed cloud IAM and live provider delivery were not exercised.
