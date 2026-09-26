import pytest

from voldemar.config import ConfigError, load_settings
from voldemar.lavalink_server import parse_java_major


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ('java version "1.8.0_431"\nJava(TM) SE Runtime Environment', 8),
        ('openjdk version "21.0.12.1" 2026-08-18 LTS\nOpenJDK Runtime Environment Temurin', 21),
        ('openjdk version "17" 2021-09-14', 17),
        ('openjdk version "25-ea" 2025-09-16', 25),
        ("something unexpected", None),
    ],
)
def test_parse_java_major(output: str, expected: int | None) -> None:
    assert parse_java_major(output) == expected


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    for name in (
        "DISCORD_TOKEN",
        "LAVALINK_PASSWORD",
        "LAVALINK_PORT",
        "ALLOW_DIRECT_LINKS",
        "APPLE_MUSIC_MEDIA_TOKEN",
        "YOUTUBE_OAUTH_ENABLED",
        "YOUTUBE_OAUTH_REFRESH_TOKEN",
        "LAVALINK_PROFILE",
        "YOUTUBE_CIPHER_URL",
        "YOUTUBE_CIPHER_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "missing.env"


def test_lavalink_env_defaults_leave_optional_tokens_unset(clean_env) -> None:
    env = load_settings(clean_env, require_token=False).lavalink_env()
    assert env["SERVER_ADDRESS"] == "127.0.0.1"
    assert env["SERVER_PORT"] == "2333"
    assert env["LAVALINK_SERVER_SOURCES_HTTP"] == "false"
    assert env["PLUGINS_YOUTUBE_OAUTH_ENABLED"] == "false"
    assert "PLUGINS_LAVASRC_APPLEMUSIC_MEDIAAPITOKEN" not in env
    assert "PLUGINS_YOUTUBE_OAUTH_REFRESHTOKEN" not in env
    assert "SPRING_PROFILES_ACTIVE" not in env  # the home setup: application.yml only
    assert "PLUGINS_YOUTUBE_REMOTECIPHER_URL" not in env


def test_lavalink_env_passes_configured_values(clean_env, monkeypatch) -> None:
    monkeypatch.setenv("LAVALINK_PASSWORD", "s3cret")
    monkeypatch.setenv("LAVALINK_PORT", "2444")
    monkeypatch.setenv("ALLOW_DIRECT_LINKS", "yes")
    monkeypatch.setenv("YOUTUBE_OAUTH_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_OAUTH_REFRESH_TOKEN", "1//token")
    settings = load_settings(clean_env, require_token=False)
    env = settings.lavalink_env()
    assert settings.lavalink_uri == "http://127.0.0.1:2444"
    assert env["LAVALINK_SERVER_PASSWORD"] == "s3cret"
    assert env["LAVALINK_SERVER_SOURCES_HTTP"] == "true"
    assert env["PLUGINS_YOUTUBE_OAUTH_ENABLED"] == "true"
    assert env["PLUGINS_YOUTUBE_OAUTH_REFRESHTOKEN"] == "1//token"


def test_cloud_profile_and_cipher_are_passed_to_lavalink(clean_env, monkeypatch) -> None:
    monkeypatch.setenv("LAVALINK_PROFILE", "cloud")
    monkeypatch.setenv("YOUTUBE_CIPHER_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("YOUTUBE_CIPHER_TOKEN", "cipher-secret")
    env = load_settings(clean_env, require_token=False).lavalink_env()
    assert env["SPRING_PROFILES_ACTIVE"] == "cloud"
    assert env["PLUGINS_YOUTUBE_REMOTECIPHER_URL"] == "http://127.0.0.1:8001"
    assert env["PLUGINS_YOUTUBE_REMOTECIPHER_PASSWORD"] == "cipher-secret"


def test_unknown_profile_is_rejected(clean_env, monkeypatch) -> None:
    monkeypatch.setenv("LAVALINK_PROFILE", "clud")  # a typo Lavalink itself would ignore
    with pytest.raises(ConfigError, match=r"application-clud\.yml"):
        load_settings(clean_env, require_token=False)
