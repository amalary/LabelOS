# Creative Memory Integration

Creative Memory is planned as a future system for capturing and retrieving
creative context across profiles, workspaces, and media. This document defines
the profile-system integration boundary only. It does not introduce Creative
Memory storage, retrieval, embeddings, or AI workflows.

## Boundary

Creative Memory data must live outside `UniversalProfile` and outside profile
module tables such as `ArtistProfile`.

`UniversalProfile` remains the durable person identity record. `ArtistProfile`
remains an optional artist-specific profile module. Creative Memory may
reference either profile through stable IDs, but profiles should not own memory
records or depend on vector, embedding, or model-provider infrastructure.

## Stable References

Future Creative Memory records can reference profile-system entities with these
IDs:

- `universal_profile_id` for person-level memory.
- `artist_profile_id` for artist-module-specific memory.
- `workspace_id` for tenant and collaboration scope.
- Domain resource IDs for media, songs, images, videos, notes, references, or
  other catalog objects when those tables exist.

These IDs should be stored on future Creative Memory tables as foreign keys or
validated external references owned by the Creative Memory subsystem. The
profile tables should not add columns such as `creative_memory`, `memory`,
`embedding_id`, `vector_namespace`, `insights`, or provider-specific metadata.

## Suggested Future Shape

A future Creative Memory subsystem can add its own package or module with tables
similar to:

- `creative_memory_records`: canonical memory entries, scoped by
  `workspace_id`, optionally linked to `universal_profile_id` and/or
  `artist_profile_id`.
- `creative_memory_sources`: source links to media items, songs, images, videos,
  notes, inspiration, references, creative eras, aesthetic preferences, or user
  annotations.
- `creative_memory_insights`: generated summaries or recommendations derived
  from records.
- `creative_memory_embeddings`: optional embedding metadata or pointers if and
  when vector search is introduced.

Those names are illustrative, not a migration plan. Do not create these tables
until product behavior, retention rules, permissions, and query patterns are
defined.

## Integration Points

Use profile IDs as inputs to Creative Memory services rather than attaching
memory behavior to profile models:

- Profile API routes can expose IDs already needed by clients, such as
  `UniversalProfile.id` and `ArtistProfile.id`.
- Creative Memory API routes can accept `workspace_id`, `universal_profile_id`,
  and `artist_profile_id` as filters.
- Authorization should be evaluated through existing workspace membership and
  profile permissions before memory records are read or mutated.
- Realtime events can be added later under a separate namespace such as
  `creative_memory.*` if clients need cache invalidation.
- Profile completion logic should not require Creative Memory. Memory-derived
  suggestions can be layered into the product experience later without changing
  profile completeness rules.

## Coupling Rules

Keep these boundaries when Creative Memory is implemented:

- Do not add Creative Memory JSON blobs to `UniversalProfile`.
- Do not add AI-provider fields, embedding vectors, or retrieval configuration
  to `UniversalProfile` or `ArtistProfile`.
- Do not make profile model construction depend on Creative Memory services.
- Do not require every profile to have memory records.
- Do not assume one memory record belongs to only one source type; support source
  references through a dedicated memory-owned association design.
- Keep vector database selection behind the Creative Memory subsystem. The
  profile system should only know stable relational IDs.

## Migration Guidance

When implementation begins, introduce Creative Memory with independent
migrations and repository/service boundaries:

1. Create memory-owned database tables with nullable foreign keys to
   `universal_profiles.id` and `artist_profiles.id` where needed.
2. Add indexes for `workspace_id`, `universal_profile_id`, `artist_profile_id`,
   source type, source ID, and lifecycle status based on actual queries.
3. Add API schemas that return memory records separately from profile responses.
4. Add permissions and tests for workspace isolation before adding generated
   insights.
5. Add embeddings only after retrieval requirements are known.

This keeps Universal Profile and Artist Profile stable while allowing Creative
Memory to connect through existing IDs later.
