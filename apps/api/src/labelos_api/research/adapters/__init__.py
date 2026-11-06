"""Explicitly composed public music adapters; importing performs no network I/O."""

from labelos_api.research.adapters.lastfm import LastFMAdapter
from labelos_api.research.adapters.musicbrainz import MusicBrainzAdapter
from labelos_api.research.adapters.songkick import SongkickAdapter
from labelos_api.research.adapters.soundcloud import SoundCloudAdapter
from labelos_api.research.adapters.spotify import SpotifyAdapter
from labelos_api.research.adapters.web import WikidataAdapter
from labelos_api.research.adapters.youtube import YouTubeAdapter

__all__ = [
    "LastFMAdapter",
    "MusicBrainzAdapter",
    "SongkickAdapter",
    "SoundCloudAdapter",
    "SpotifyAdapter",
    "WikidataAdapter",
    "YouTubeAdapter",
]
