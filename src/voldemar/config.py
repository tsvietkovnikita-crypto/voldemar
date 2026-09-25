"""Settings loaded from environment variables, with an optional `.env` file in the project root."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(Exception):
    """A setting is missing or invalid. The message is shown to the user as-is."""


def _get_str(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default


def _get_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = _get_str(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}.") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}, got {value}.")
    return value


def _get_bool(name: str, default: bool) -> bool:
    raw = _get_str(name).lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false, got {raw!r}.")


def _get_ids(name: str) -> tuple[int, ...]:
    ids: list[int] = []
    for part in _get_str(name).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ConfigError(
                f"{name} must be a comma-separated list of numeric server IDs, got {part!r}."
            )
        ids.append(int(part))
    return tuple(ids)


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    guild_ids: tuple[int, ...]
    lavalink_host: str
    lavalink_port: int
    lavalink_password: str
    lavalink_autostart: bool
    java_path: str
    default_volume: int
    max_queue_size: int
    idle_timeout: int
    empty_channel_timeout: int
    apple_music_country: str
    apple_music_media_token: str
    youtube_oauth_enabled: bool
    youtube_oauth_refresh_token: str

    @property
    def lavalink_uri(self) -> str:
        return f"http://{self.lavalink_host}:{self.lavalink_port}"

    def lavalink_env(self) -> dict[str, str]:
        """Variables that `lavalink/application.yml` reads through its `${...}` placeholders."""
        return {
            "LAVALINK_HOST": self.lavalink_host,
            "LAVALINK_PORT": str(self.lavalink_port),
            "LAVALINK_PASSWORD": self.lavalink_password,
            "APPLE_MUSIC_COUNTRY": self.apple_music_country,
            "APPLE_MUSIC_MEDIA_TOKEN": self.apple_music_media_token,
            "YOUTUBE_OAUTH_ENABLED": str(self.youtube_oauth_enabled).lower(),
            "YOUTUBE_OAUTH_REFRESH_TOKEN": self.youtube_oauth_refresh_token,
        }


def load_settings(env_file: Path | None = None) -> Settings:
    """Read settings; values already present in the environment win over the `.env` file."""
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)

    token = _get_str("DISCORD_TOKEN")
    if not token:
        raise ConfigError(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and paste your bot token into it "
            "(Discord Developer Portal -> your application -> Bot -> Reset Token)."
        )

    country = _get_str("APPLE_MUSIC_COUNTRY", "US").upper()
    if len(country) != 2 or not country.isalpha():
        raise ConfigError(
            f"APPLE_MUSIC_COUNTRY must be a two-letter country code, got {country!r}."
        )

    return Settings(
        discord_token=token,
        guild_ids=_get_ids("GUILD_IDS"),
        lavalink_host=_get_str("LAVALINK_HOST", "127.0.0.1"),
        lavalink_port=_get_int("LAVALINK_PORT", 2333, minimum=1, maximum=65535),
        lavalink_password=_get_str("LAVALINK_PASSWORD", "youshallnotpass"),
        lavalink_autostart=_get_bool("LAVALINK_AUTOSTART", True),
        java_path=_get_str("JAVA_PATH"),
        default_volume=_get_int("DEFAULT_VOLUME", 80, minimum=0, maximum=150),
        max_queue_size=_get_int("MAX_QUEUE_SIZE", 500, minimum=1, maximum=5000),
        idle_timeout=_get_int("IDLE_TIMEOUT", 180, minimum=10, maximum=86400),
        empty_channel_timeout=_get_int("EMPTY_CHANNEL_TIMEOUT", 60, minimum=5, maximum=86400),
        apple_music_country=country,
        apple_music_media_token=_get_str("APPLE_MUSIC_MEDIA_TOKEN"),
        youtube_oauth_enabled=_get_bool("YOUTUBE_OAUTH_ENABLED", False),
        youtube_oauth_refresh_token=_get_str("YOUTUBE_OAUTH_REFRESH_TOKEN"),
    )
