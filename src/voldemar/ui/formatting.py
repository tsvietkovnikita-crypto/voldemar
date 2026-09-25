"""Text helpers for durations, progress bars and track titles in Discord messages."""

from __future__ import annotations

import re

from discord.utils import escape_markdown

from voldemar.music.queue import QueueEntry

SOURCE_NAMES = {
    "youtube": "YouTube",
    "spotify": "Spotify",
    "applemusic": "Apple Music",
    "soundcloud": "SoundCloud",
    "bandcamp": "Bandcamp",
    "twitch": "Twitch",
    "vimeo": "Vimeo",
    "http": "Direct link",
}


def format_duration(ms: int) -> str:
    seconds = max(ms, 0) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def entry_duration(entry: QueueEntry) -> str:
    return "LIVE" if entry.is_stream else format_duration(entry.length_ms)


def parse_time(text: str) -> int:
    """Milliseconds from "83", "1:23", "1:02:03" or "1m23s"; raises ValueError otherwise."""
    text = text.strip().lower()
    if re.fullmatch(r"\d+(?::\d{1,2}){0,2}", text):
        first, *rest = (int(p) for p in text.split(":"))
        if any(p >= 60 for p in rest):
            raise ValueError(text)
        seconds = first
        for part in rest:
            seconds = seconds * 60 + part
        return seconds * 1000
    match = re.fullmatch(r"(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?", text)
    if match and any(match.groups()):
        hours, minutes, seconds = (int(g or 0) for g in match.groups())
        return ((hours * 60 + minutes) * 60 + seconds) * 1000
    raise ValueError(text)


def progress_bar(position_ms: int, length_ms: int, width: int = 16) -> str:
    if length_ms <= 0:
        return "🔴 LIVE"
    ratio = min(max(position_ms / length_ms, 0.0), 1.0)
    filled = round(ratio * (width - 1))
    bar = "▬" * filled + "🔘" + "▬" * (width - 1 - filled)
    return f"{bar} `{format_duration(position_ms)} / {format_duration(length_ms)}`"


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def entry_link(entry: QueueEntry, limit: int = 70) -> str:
    """The title as a markdown link (when it has a URL), safe to embed in a message."""
    title = escape_markdown(truncate(entry.title, limit).replace("[", "(").replace("]", ")"))
    return f"[{title}]({entry.uri})" if entry.uri else f"**{title}**"


def entry_line(entry: QueueEntry, limit: int = 60) -> str:
    author = escape_markdown(truncate(entry.author, 40))
    return f"{entry_link(entry, limit)} — {author} `{entry_duration(entry)}`"


def source_name(entry: QueueEntry) -> str:
    return SOURCE_NAMES.get(entry.source, entry.source.title())
