"""Entry point for `uv run voldemar`."""

from __future__ import annotations

import io
import logging
import sys
from logging.handlers import RotatingFileHandler

import discord

from voldemar.bot import VoldemarBot
from voldemar.config import PROJECT_ROOT, ConfigError, load_settings

log = logging.getLogger("voldemar")


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


def main() -> None:
    setup_logging()
    try:
        settings = load_settings()
    except ConfigError as e:
        log.error("%s", e)
        sys.exit(1)

    bot = VoldemarBot(settings)
    try:
        bot.run(settings.discord_token, log_handler=None)
    except discord.LoginFailure:
        log.error(
            "Discord rejected DISCORD_TOKEN. Reset it in the Developer Portal and update .env."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
