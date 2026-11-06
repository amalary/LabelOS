"""One live public lookup through the API's MusicBrainz composition.

Run explicitly: python apps/api/scripts/musicbrainz_smoke.py
Loads only MusicBrainz configuration from the root .env. No database, auth token,
cloud credential store, production state, or Desktop credential file is accessed.
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "packages/database/src")]

from labelos_api.config import Settings  # noqa: E402
from labelos_api.research.contracts import (  # noqa: E402
    ArtistLookupRequest,
    CollectionContext,
)
from labelos_api.research.errors import ProviderError  # noqa: E402
from labelos_api.research.musicbrainz import (  # noqa: E402
    MusicBrainzNotConfigured,
    build_musicbrainz_client,
)


async def main():
    profile = dotenv_values(ROOT / ".env", interpolate=False)
    settings = Settings(
        environment="local",
        musicbrainz_base_url=profile.get("MUSICBRAINZ_BASE_URL")
        or "https://musicbrainz.org/ws/2",
        musicbrainz_user_agent=profile.get("MUSICBRAINZ_USER_AGENT"),
        musicbrainz_approval_ref=profile.get("MUSICBRAINZ_APPROVAL_REF"),
    )
    context = CollectionContext(
        workspace_id=uuid4(),
        provider_id=uuid4(),
        provider_key="musicbrainz",
        collection_run_id=uuid4(),
        dataset_version_id=uuid4(),
    )
    client = build_musicbrainz_client(settings, context)
    # Stable public identity; no user data or private search terms are sent.
    mbid = "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d"
    result = await client.lookup_artist(
        ArtistLookupRequest(artist_id=mbid), context=context
    )
    if result.artist.external_id != mbid or result.artist.name != "The Beatles":
        raise RuntimeError("Unexpected public identity in smoke-test response")
    print("PASS: live MusicBrainz lookup returned The Beatles through ProviderClient.")
    print(f"Verified MBID: {mbid}")
    print("Authentication: none. Database/cloud writes: none.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MusicBrainzNotConfigured:
        print(
            "MusicBrainz is not configured; check contact and permitted-use reference."
        )
        sys.exit(1)
    except ProviderError as error:
        print(f"MusicBrainz live check failed: {error.failure.details.code.value}")
        sys.exit(1)
    except Exception:
        print(
            "MusicBrainz live check failed; details withheld to protect local settings."
        )
        sys.exit(1)
