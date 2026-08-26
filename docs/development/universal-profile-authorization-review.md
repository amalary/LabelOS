# Universal Profile Authorization Security Review

Date: 2026-08-25

## Authorization Model Confirmed

- Authentication is provided by WorkOS AuthKit access tokens.
- Authorization is enforced by LabelOS local workspace membership state and
  capability policies.
- Frontend route protection is treated as advisory. Backend APIs must enforce
  the same workspace and capability constraints for direct calls.

## Findings

### Profile ID enumeration through direct profile reads

`GET /api/v1/profiles/{profile_id}` returned any universal profile to any
authenticated caller. This allowed profile UUID probing across workspaces.

Fix: direct profile reads now require either profile ownership or an active
shared workspace membership. The check revalidates the caller's active
membership in the database before returning another user's profile.

Regression tests:

- `test_direct_profile_read_hides_profiles_without_shared_workspace`
- `test_direct_profile_read_allows_shared_workspace_member`
- `test_direct_profile_read_rechecks_removed_actor_membership`

### Workspace role assignment used administrative checks instead of capability policy

Role assignment and removal required local admin-like membership plus WorkOS
member-management permission. The Universal Profile policy model requires local
`role.assign` capability authorization.

Fix: role assignment and removal now require an active database membership for
the actor and the LabelOS `role.assign` capability for the workspace.

Regression test:

- `test_assign_workspace_role_requires_labelos_role_assign_capability`

### Self permission escalation by role assignment

A caller with access to the role assignment endpoint could assign workspace
roles to their own membership.

Fix: role assignment and removal reject operations targeting the caller's own
membership.

Regression test:

- `test_assign_workspace_role_rejects_self_escalation`

### Removed memberships and stale authorization context

Role assignment relied on the request context for membership and capability
state. A stale context could continue to authorize after the actor was removed,
and removed target memberships could still be mutated.

Fix: role assignment and removal recheck active actor membership in the database
and reject inactive or removed target memberships.

Regression tests:

- `test_assign_workspace_role_rechecks_removed_actor_membership`
- `test_assign_workspace_role_rejects_removed_target_membership`

## Reviewed Scenarios

- User accessing another workspace: workspace profile list/detail endpoints
  require active workspace membership and hide misses as `404`.
- User editing another person's profile: profile mutation is limited to
  `/profiles/me`; WorkOS-managed identity fields are rejected.
- User assigning roles without permission: fixed to require local `role.assign`.
- User escalating their own permissions: fixed by rejecting self role assignment.
- Removed user retaining access: fixed for direct profile reads and role
  assignment by rechecking database membership; realtime already rechecks
  membership during streams.
- Expired invitation acceptance: existing behavior returns `410` and marks
  expired active invites.
- Forged workspace ID: workspace-scoped APIs require active membership for the
  supplied workspace ID.
- Direct API calls bypassing frontend restrictions: fixed backend enforcement
  for vulnerable direct profile and role assignment calls.
- Capability cache becoming stale: request context is not treated as sufficient
  for the updated sensitive checks; active membership is revalidated in the
  database.
- Profile IDs being enumerated: fixed by scoped direct profile reads.
- Deleted membership retaining websocket access: existing realtime stream
  checks active database membership before opening and periodically during the
  stream.
