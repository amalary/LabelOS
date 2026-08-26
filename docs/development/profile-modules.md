# Profile Modules

UniversalProfile is the common identity record for a person in LabelOS. It owns
shared identity fields such as display name, legal name parts, biography,
avatar, location, timezone, primary email, profile status, onboarding status,
links, attributes, preferences, and workspace memberships.

UniversalProfile is independent of workspace hierarchy. Workspace-specific state
must remain on `workspace_memberships` or a workspace-owned table, with
membership records referencing workspaces by stable `workspace_id` values. See
`docs/development/enterprise-hierarchy-extension.md` for the future enterprise
extension path.

Specialized profile data lives in optional profile module tables. A profile can
have no modules, one module, or several modules when the same person has
multiple domain roles.

## Current Module

`ArtistProfile` is the first concrete profile module.

It stores artist-specific data only:

- `stage_name`
- `genres`
- `influences`
- `imagery`
- `dsp_links`
- `catalog_references`
- `creative_metadata`
- `career_stage`
- `audience`
- `preferences`

It does not store common identity fields such as display name, first name, last
name, primary email, avatar, location, timezone, or biography. Those remain on
`UniversalProfile`.

Each `ArtistProfile` row must reference `universal_profile_id`. Its `artist_id`
links the module to the label catalog artist resource. Catalog artists may exist
without an ArtistProfile module.

## Artist Profile Ownership Contract

`Artist` and `ArtistProfile` are intentionally different records:

- `Artist` is the workspace-owned catalog resource. It can represent a roster
  artist, prospect, historical catalog entry, or planning placeholder. It does
  not require a LabelOS user account or Universal Profile.
- `ArtistProfile` is a person-backed profile module. It must point to exactly
  one `UniversalProfile`, and it may link to one catalog `Artist` through
  `artist_id`.

Do not infer `ArtistProfile.universal_profile_id` from artist name,
organization owner, professional role, or invite metadata. Create an
ArtistProfile only when onboarding, an admin action, or another deterministic
source explicitly maps the catalog artist to a Universal Profile.

Artist Profile API behavior must preserve this distinction:

- creating or updating catalog artist fields must not require a Universal
  Profile;
- creating artist-module fields must require `universal_profile_id`;
- a supplied Universal Profile must belong to the target workspace through an
  active `WorkspaceMembership`;
- deleting a catalog artist may delete its ArtistProfile through the catalog
  relationship, but deleting an ArtistProfile must not delete the Universal
  Profile or user account.

## Model Contract

New modules should use `ProfileModuleMixin` from
`packages/database/src/labelos_database/models.py`.

The mixin provides:

- `id`
- required `universal_profile_id`
- `universal_profile` relationship

Each module then defines only its specialized fields and any domain-resource
links it needs.

## Creative Memory Boundary

Creative Memory is a future subsystem, not a profile module. Do not store memory
records, embeddings, generated insights, media references, inspiration, creative
eras, or AI-provider metadata on `UniversalProfile` or `ArtistProfile`.

Future Creative Memory records should reference profile-system entities through
stable IDs such as `universal_profile_id`, `artist_profile_id`, and
`workspace_id`. Keep the memory schema and any vector infrastructure in a
memory-owned package or service so profile models remain identity and
role-module records only.

See `docs/development/creative-memory-integration.md` for the suggested
integration boundary.

## Adding Another Module

For a future module such as `ManagerProfile`, use this sequence:

1. Add a `manager_profiles` relationship to `UniversalProfile`.
2. Add `"manager_profiles"` to `PROFILE_MODULE_RELATIONSHIPS`.
3. Create a `ManagerProfile(Base, TimestampMixin, ProfileModuleMixin)` model.
4. Set `__profile_module_key__ = "manager"` and
   `__universal_profile_relationship__ = "manager_profiles"`.
5. Add only manager-specific columns. Do not copy common identity fields from
   `UniversalProfile`.
6. Add an Alembic migration that creates `manager_profiles` with a required
   `universal_profile_id` foreign key to `universal_profiles.id`.
7. Export the model from `labelos_database.__init__`.
8. Add model and relationship tests similar to the ArtistProfile coverage in
   `apps/api/tests/test_database_foundation.py`.
9. Add API schemas/routes only when the product flow needs to read or mutate
   that module.

Use the same pattern for ProducerProfile, ExecutiveProfile, EmployeeProfile, or
ContributorProfile. Do not add empty tables for those modules until there is a
real field contract or workflow for them.
