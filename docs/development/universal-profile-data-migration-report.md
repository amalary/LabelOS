# Universal Profile Data Migration Report

Date: 2026-08-25

## Scope

This report covers the migration strategy for existing LabelOS identity data into
Universal Profiles while keeping the current WorkOS-backed user, organization,
membership, and catalog artist records intact.

The migration must not remove old user, organization membership, or artist fields
until the Universal Profile system is stable in production.

## Current State Reviewed

- `users.id` is the durable local user ID. `users.workos_user_id` remains the
  external WorkOS user relationship and is unique when present.
- `universal_profiles.user_id` is required and unique, giving each user at most
  one Universal Profile.
- `organization_memberships` preserves the current WorkOS-backed membership
  relationship through `organization_id`, `user_id`, `workos_membership_id`,
  role, workspace permission, status, department access, and capability grants.
- `workspace_memberships` is the newer profile-facing membership projection. It
  references `universal_profiles.id`, keeps a nullable
  `organization_membership_id` compatibility link, and has unique constraints on
  both `(workspace_id, profile_id)` and `organization_membership_id`.
- `artists` are existing organization-owned catalog resources. They must remain
  authoritative for catalog artist identity and must not be deleted or re-keyed.
- `artist_profiles` are optional profile modules. The model requires each
  Artist Profile to reference `universal_profile_id`.

Migration safety rule: catalog artist rows must not be converted into
`artist_profiles` unless a deterministic Universal Profile link exists. The
artist profile migration creates the module table but does not backfill
placeholder rows for existing catalog artists. Catalog artists without a person
profile remain valid `artists` rows.

## Migration Strategy

1. Take a pre-migration backup and record baseline counts.

   Required baseline counts:

   ```sql
   SELECT count(*) AS users_count FROM users;
   SELECT count(*) AS universal_profiles_count FROM universal_profiles;
   SELECT count(*) AS organizations_count FROM organizations;
   SELECT count(*) AS organization_memberships_count FROM organization_memberships;
   SELECT count(*) AS workspace_memberships_count FROM workspace_memberships;
   SELECT count(*) AS artists_count FROM artists;
   SELECT count(*) AS artist_profiles_count FROM artist_profiles;
   ```

2. Backfill one Universal Profile per existing user.

   Preserve `users.id`; do not generate replacement users. Populate profile
   identity fields from the existing user row:

   - `user_id = users.id`
   - `display_name = users.display_name`
   - `first_name = users.first_name`
   - `last_name = users.last_name`
   - `avatar_url = users.profile_image_url`
   - `primary_email = users.email`
   - `profile_status = 'active'`
   - `onboarding_status = 'not_started'`

   The backfill must be idempotent by selecting only users without an existing
   Universal Profile and by relying on `uq_universal_profiles_user_id` as the
   final duplicate guard.

3. Preserve WorkOS relationships without rewriting them.

   Do not update or normalize these values in the Universal Profile migration:

   - `users.workos_user_id`
   - `organizations.workos_organization_id`
   - `organization_memberships.workos_membership_id`
   - `organization_memberships.organization_id`
   - `organization_memberships.user_id`

   These remain the compatibility records used by WorkOS AuthKit and WorkOS
   webhook synchronization.

4. Backfill workspace memberships from organization memberships.

   For each `organization_memberships` row, resolve the user's Universal Profile
   and insert one `workspace_memberships` row:

   - `workspace_id = organization_memberships.organization_id`
   - `profile_id = universal_profiles.id`
   - `organization_membership_id = organization_memberships.id`
   - `status = organization_memberships.status`
   - `joined_at = now()` only for active or accepted memberships

   Make the operation idempotent by first matching on
   `organization_membership_id`, then on `(workspace_id, profile_id)`. If an
   existing row is found, update the compatibility link and status instead of
   inserting a duplicate.

5. Preserve existing artist records.

   Do not delete from `artists`. Catalog artist records are organization-owned
   resources and may exist without a person-backed Artist Profile module.

   If an existing Artist Profile can be deterministically linked to a user,
   create or repair the `artist_profiles` row with
   `artist_profiles.universal_profile_id` set to that user's Universal Profile.
   A link is deterministic only when an existing data source already identifies
   the person-user relationship. The current `artists` table only stores
   `organization_id` and `name`, so it is not safe to infer a Universal Profile
   from artist name, organization owner, or membership role alone.

   For catalog artists without a deterministic user link, keep the `artists` row
   and skip Artist Profile creation until onboarding or an admin action supplies
   the person mapping.

6. Enforce Artist Profile integrity only after backfill validation.

   Before relying on `artist_profiles.universal_profile_id` non-null behavior,
   validate:

   ```sql
   SELECT count(*) AS unlinked_artist_profiles
   FROM artist_profiles
   WHERE universal_profile_id IS NULL;
   ```

   If the count is non-zero, either keep `artist_profiles.universal_profile_id`
   nullable temporarily or move unlinked module rows into an explicit recovery
   table before tightening the constraint. Do not delete them as part of the
   migration.

## Recommended Alembic Shape

Use one additive data migration after the Universal Profile and
WorkspaceMembership tables exist, before any non-null Artist Profile enforcement:

1. Create any missing Universal Profiles for `users`.
2. Upsert or repair WorkspaceMembership rows from `organization_memberships`.
3. Backfill ArtistProfile `universal_profile_id` only from deterministic legacy
   mappings.
4. Emit count validation failures by raising from the migration if required
   invariants do not hold.
5. Leave old user and membership fields in place.

The migration should use SQLAlchemy/Alembic connection operations and generated
UUIDs, matching the existing migration style. If PostgreSQL-specific upsert SQL
is used, keep unique constraints as the authoritative duplicate prevention:

- `uq_universal_profiles_user_id`
- `uq_organization_memberships_organization_id_user_id`
- `uq_organization_memberships_workos_membership_id`
- `uq_workspace_memberships_workspace_id_profile_id`
- `uq_workspace_memberships_organization_membership_id`
- `uq_artist_profiles_artist_id`

## Validation Checks

Run these checks immediately after migration:

```sql
-- Every user has exactly one Universal Profile.
SELECT count(*) AS users_without_profile
FROM users u
LEFT JOIN universal_profiles up ON up.user_id = u.id
WHERE up.id IS NULL;

SELECT user_id, count(*) AS profile_count
FROM universal_profiles
GROUP BY user_id
HAVING count(*) > 1;

-- WorkOS user links were preserved.
SELECT count(*) AS workos_users_missing_after_migration
FROM users
WHERE workos_user_id IS NOT NULL;

-- Every organization membership has a profile-backed workspace membership.
SELECT count(*) AS memberships_without_workspace_membership
FROM organization_memberships om
LEFT JOIN workspace_memberships wm
  ON wm.organization_membership_id = om.id
WHERE wm.id IS NULL;

-- No duplicate workspace memberships for the same profile in a workspace.
SELECT workspace_id, profile_id, count(*) AS duplicate_count
FROM workspace_memberships
GROUP BY workspace_id, profile_id
HAVING count(*) > 1;

-- Existing artists were preserved.
SELECT count(*) AS artists_count FROM artists;

-- Artist Profiles either have valid profile links or remain intentionally nullable.
SELECT count(*) AS artist_profiles_with_missing_profile
FROM artist_profiles ap
LEFT JOIN universal_profiles up ON up.id = ap.universal_profile_id
WHERE ap.universal_profile_id IS NOT NULL
  AND up.id IS NULL;
```

Expected results:

- `users_without_profile = 0`
- no duplicate `universal_profiles.user_id`
- `memberships_without_workspace_membership = 0`, except intentionally excluded
  legacy rows documented before migration
- no duplicate `(workspace_id, profile_id)` rows
- post-migration `artists_count` equals the pre-migration `artists_count`
- no Artist Profile points at a missing Universal Profile

## Rollback And Recovery

Because this migration is additive, preferred recovery is forward repair:

1. Keep the database backup until production validation passes.
2. Keep all old columns and legacy tables active.
3. If Universal Profile backfill is incomplete, rerun the idempotent migration or
   a targeted repair for missing `users.id` values.
4. If workspace membership projection is incomplete, rerun the projection repair
   from `organization_memberships`.
5. If an Artist Profile was linked incorrectly, clear or update only
   `artist_profiles.universal_profile_id`; do not delete the `artists` row.
6. If a release must be rolled back, deploy application code that reads the old
   user and organization membership fields while leaving the new tables in
   place, then clean up after a separate data review.

Destructive rollback should be a last resort and should only remove rows created
by the migration after joining against a captured migration batch manifest. Do
not drop `users`, `organizations`, `organization_memberships`, or `artists`, and
do not rewrite their IDs.

## Stability Gates Before Removing Old Fields

Old fields should remain until all of these are true for at least one production
release cycle:

- Authentication and WorkOS webhook flows continue to resolve the same local
  `users.id`.
- Organization switching and authorization resolve through workspace membership
  without losing role, permission, department, or status behavior.
- Profile reads and writes use `universal_profiles.id` where intended.
- Artist workflows preserve all existing `artists.id` references from releases,
  contracts, royalties, analytics, and dashboard surfaces.
- Validation queries show no missing profiles, duplicate profiles, duplicate
  workspace memberships, or orphaned Artist Profile links.
