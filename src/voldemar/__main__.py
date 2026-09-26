"""Entry point for `uv run voldemar`."""

from __future__ import annotations

import io
import logging
import sys
from logging.handlers import RotatingFileHandler

import discord

from voldemar import lavalink_server
from voldemar.bot import VoldemarBot
from voldemar.config import PROJECT_ROOT, ConfigError, Settings, load_settings
from voldemar.lavalink_server import LavalinkError, LavalinkProcess

log = logging.getLogger("voldemar")

# "Configuration error" (sysexits EX_CONFIG). deploy/voldemar.service doesn't restart on it,
# since retrying can't fix a missing or rejected token.
EXIT_CONFIG = 78


def setup_logging() -> None:
    # Track titles contain emoji and non-Latin text; a legacy console code page must not break logs.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")

    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logfile = RotatingFileHandler(
        logs_dir / "voldemar.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    logfile.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[console, logfile])
    # wavelink logs each failed track with Lavalink's full multi-kilobyte report; cogs/events.py
    # logs one line instead, and the full report stays in logs/lavalink.log.
    logging.getLogger("TrackException").setLevel(logging.CRITICAL)


def start_lavalink(settings: Settings) -> LavalinkProcess | None:
    """Start Lavalink unless it is already running or autostart is off; return what we started."""
    if lavalink_server.probe(settings):
        log.info("Using the Lavalink already running on %s", settings.lavalink_uri)
        return None
    if not settings.lavalink_autostart:
        log.warning(
            "Lavalink isn't running on %s; waiting for it to come up", settings.lavalink_uri
        )
        return None

    process = LavalinkProcess(settings)
    try:
        process.start()
        process.wait_until_ready()
    except BaseException:
        process.stop()
        raise
    return process


def main() -> None:
    setup_logging()
    try:
        settings = load_settings()
        lavalink = start_lavalink(settings)
    except ConfigError as e:
        log.error("%s", e)
        sys.exit(EXIT_CONFIG)
    except LavalinkError as e:
        log.error("%s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)

    try:
        VoldemarBot(settings).run(settings.discord_token, log_handler=None)
    except discord.LoginFailure:
        log.error(
            "Discord rejected DISCORD_TOKEN. Reset it in the Developer Portal and update .env."
        )
        sys.exit(EXIT_CONFIG)
    finally:
        if lavalink is not None:
            lavalink.stop()


if __name__ == "__main__":
    main()
