import importlib.util
import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from labelos_api.config import Settings, get_settings
from labelos_api.main import create_app
from labelos_api.research.adapters.musicbrainz import MusicBrainzAdapter


@pytest.mark.parametrize("key", [None, ""])
def test_missing_lastfm_credentials_allow_startup(monkeypatch, key):
    if key is None:
        monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    else:
        monkeypatch.setenv("LASTFM_API_KEY", key)
    monkeypatch.delenv("MUSICBRAINZ_BASE_URL", raising=False)
    monkeypatch.delenv("MUSICBRAINZ_USER_AGENT", raising=False)

    settings = get_settings()
    assert settings.lastfm_api_key is None
    assert settings.musicbrainz_user_agent is None
    assert settings.musicbrainz_base_url + "/" == MusicBrainzAdapter.base_url
    assert MusicBrainzAdapter.descriptor.authentication.method == "none"
    settings.validate_startup_environment()
    assert create_app().title == settings.app_name


def test_music_settings_load_without_exposing_lastfm_key(monkeypatch):
    monkeypatch.setenv("MUSICBRAINZ_BASE_URL", "https://musicbrainz.org/ws/2")
    monkeypatch.setenv("MUSICBRAINZ_USER_AGENT", "LabelOS/0.1 (fixtures@example.test)")
    monkeypatch.setenv("LASTFM_API_KEY", "synthetic-lastfm-test-key")

    settings = get_settings()
    assert settings.musicbrainz_user_agent == "LabelOS/0.1 (fixtures@example.test)"
    assert settings.lastfm_api_key.get_secret_value() == "synthetic-lastfm-test-key"
    assert "lastfm_api_key" not in settings.model_dump()
    for rendered in (repr(settings), str(settings), settings.model_dump_json()):
        assert "synthetic-lastfm-test-key" not in rendered
    assert "synthetic-lastfm-test-key" not in str(settings.lastfm_api_key)
    assert "lastfm_api_key" not in str(create_app().openapi())


def test_musicbrainz_origin_cannot_be_redirected(monkeypatch):
    monkeypatch.setenv("MUSICBRAINZ_BASE_URL", "https://proxy.example.test/ws/2")
    with pytest.raises(ValidationError):
        get_settings()


def test_existing_local_launcher_loads_music_and_preserves_other_settings(
    monkeypatch, tmp_path
):
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "local_database_music_settings_test", root / "scripts/local_database.py"
    )
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(sys, "path", sys.path.copy())
    (tmp_path / ".env.labelos-local").write_text(
        "DATABASE_URL=postgresql+asyncpg://labelos:synthetic-test-password"
        "@127.0.0.1:55432/labelos_ar_dev\n"
    )
    (tmp_path / ".env").write_text(
        "MUSICBRAINZ_BASE_URL=https://musicbrainz.org/ws/2\n"
        "MUSICBRAINZ_USER_AGENT=LabelOS/0.1 (fixtures@example.test)\n"
        "LASTFM_API_KEY=\n"
        "WORKOS_CLIENT_ID=client_test\n"
        "WORKOS_API_KEY=synthetic-workos-test-key\n"
        "YOUTUBE_OAUTH_CLIENT_ID=synthetic-youtube-client\n"
        "YOUTUBE_OAUTH_CLIENT_SECRET=synthetic-youtube-secret\n"
        "CREDENTIAL_STORE_BACKEND=gcp-secret-manager\n"
        "CREDENTIAL_STORE_GCP_PROJECT_ID=project-test\n"
        "YOUTUBE_RESEARCH_LOCAL_CREDENTIAL_REF="
        "gcp-secret-manager://projects/project-test/secrets/youtube-test\n"
    )

    # configure() only loads the environment; do not call inspect() or main(),
    # which would connect to PostgreSQL or start a service.
    launcher.configure()
    settings = get_settings()
    settings.validate_startup_environment()
    assert settings.musicbrainz_base_url == "https://musicbrainz.org/ws/2"
    assert settings.musicbrainz_user_agent == "LabelOS/0.1 (fixtures@example.test)"
    assert settings.lastfm_api_key is None
    assert settings.workos_client_id == "client_test"
    assert settings.workos_api_key == "synthetic-workos-test-key"
    assert settings.youtube_oauth_client_secret == "synthetic-youtube-secret"
    assert settings.credential_store_backend == "gcp-secret-manager"
    assert settings.youtube_research_local_credential_ref == (
        "gcp-secret-manager://projects/project-test/secrets/youtube-test"
    )
    assert Settings().musicbrainz_base_url == settings.musicbrainz_base_url
