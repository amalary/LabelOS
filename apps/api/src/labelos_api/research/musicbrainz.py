"""Compose MusicBrainz with server settings and the existing provider boundary."""

import re

from labelos_api.config import Settings
from labelos_api.research.adapters.common import AccessPolicy
from labelos_api.research.adapters.musicbrainz import MusicBrainzAdapter
from labelos_api.research.contracts import CollectionContext, ProviderConfiguration
from labelos_api.research.providers import ProviderClient

LOCAL_NONCOMMERCIAL_APPROVAL = "local-noncommercial-testing"


class MusicBrainzNotConfigured(Exception):
    pass


def build_musicbrainz_client(
    settings: Settings, context: CollectionContext
) -> ProviderClient:
    agent = settings.musicbrainz_user_agent or ""
    approval = settings.musicbrainz_approval_ref
    if (
        not approval
        or not agent.isascii()
        or "\r" in agent
        or "\n" in agent
        or "REPLACE_WITH_" in agent
        or not re.search(r"\([^()\s]+@[^()\s]+\.[^()\s]+\)", agent)
        or settings.musicbrainz_base_url + "/" != MusicBrainzAdapter.base_url
        or context.provider_key != "musicbrainz"
    ):
        raise MusicBrainzNotConfigured()
    if (
        approval == LOCAL_NONCOMMERCIAL_APPROVAL
        and settings.requires_strict_startup_validation
    ):
        raise MusicBrainzNotConfigured()
    adapter = MusicBrainzAdapter(
        policy=AccessPolicy(approval_ref=approval, user_agent=agent)
    )
    # The default RequestGate is shared across requests in this process. Do not
    # create a fresh gate per client: that would bypass the one-call/second limit.
    return ProviderClient(
        adapter,
        ProviderConfiguration(
            workspace_id=context.workspace_id,
            provider_id=context.provider_id,
            provider_key="musicbrainz",
        ),
    )
