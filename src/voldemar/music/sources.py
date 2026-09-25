"""Classify what the user typed into /play and normalise links before they are loaded."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import SplitResult, parse_qs, urlencode, urlsplit, urlunsplit


class SourceKind(Enum):
    YOUTUBE = "youtube"  # youtube.com, youtu.be, music.youtube.com -> Lavalink youtube-plugin
    APPLE_MUSIC = "applemusic"  # music.apple.com -> Lavalink LavaSrc
    SPOTIFY = "spotify"  # open.spotify.com, spotify: URIs, spotify.link -> resolved by the bot
    OTHER_URL = "url"  # SoundCloud, Bandcamp, Twitch, Vimeo, ... -> Lavalink as-is
    SEARCH = "search"  # plain text -> YouTube Music search


class UnsupportedLink(ValueError):
    """A link we recognise but can't play. The message is shown to the user."""


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    kind: SourceKind
    value: str  # the normalised URL, or the search text
    spotify_type: str | None = None  # track, album, playlist or artist
    spotify_id: str | None = None

    @property
    def is_spotify_short_link(self) -> bool:
        return self.kind is SourceKind.SPOTIFY and self.spotify_id is None


MAX_SEARCH_LENGTH = 200

_YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}
_SPOTIFY_HOSTS = {"open.spotify.com", "play.spotify.com"}
_SPOTIFY_SHORT_HOSTS = {"spotify.link", "spotify.app.link"}
_APPLE_HOSTS = {"music.apple.com", "geo.music.apple.com", "itunes.apple.com"}
_SPOTIFY_TYPES = {"track", "album", "playlist", "artist"}
_APPLE_TYPES = {"album", "playlist", "artist", "song"}

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_LIST_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_SPOTIFY_ID = re.compile(r"^[A-Za-z0-9]{22}$")
_SPOTIFY_URI = re.compile(
    r"^spotify:(?:user:[^:\s]+:)?(track|album|playlist|artist):([A-Za-z0-9]{22})$"
)
_BARE_URL = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}/\S*$", re.IGNORECASE)


def spotify_url(kind: str, spotify_id: str) -> str:
    return f"https://open.spotify.com/{kind}/{spotify_id}"


def parse_query(raw: str) -> ParsedQuery:
    # People often wrap links in <...> to stop Discord from embedding them.
    text = raw.strip().removeprefix("<").removesuffix(">").strip()
    if not text:
        raise UnsupportedLink("Give me a link or something to search for.")

    if match := _SPOTIFY_URI.match(text):
        kind, spotify_id = match[1], match[2]
        return ParsedQuery(SourceKind.SPOTIFY, spotify_url(kind, spotify_id), kind, spotify_id)

    if " " not in text and _BARE_URL.match(text):
        text = "https://" + text  # "youtu.be/abc" without a scheme

    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        if len(text) > MAX_SEARCH_LENGTH:
            raise UnsupportedLink(f"That search is too long (max {MAX_SEARCH_LENGTH} characters).")
        return ParsedQuery(SourceKind.SEARCH, text)

    host = parts.hostname.removeprefix("www.")
    if host in _YOUTUBE_HOSTS or host == "youtu.be":
        return _parse_youtube(parts, host)
    if host in _SPOTIFY_HOSTS:
        return _parse_spotify(parts)
    if host in _SPOTIFY_SHORT_HOSTS:
        return ParsedQuery(SourceKind.SPOTIFY, urlunsplit(parts._replace(scheme="https")))
    if host in _APPLE_HOSTS:
        return _parse_apple(parts)
    return ParsedQuery(SourceKind.OTHER_URL, text)


def _youtube_video(video_id: str) -> ParsedQuery:
    return ParsedQuery(
        SourceKind.YOUTUBE, "https://www.youtube.com/watch?" + urlencode({"v": video_id})
    )


def _parse_youtube(parts: SplitResult, host: str) -> ParsedQuery:
    segments = [s for s in parts.path.split("/") if s]
    query = parse_qs(parts.query)

    if host == "youtu.be" and segments and _VIDEO_ID.match(segments[0]):
        return _youtube_video(segments[0])
    if parts.path == "/watch" and "v" in query:
        # A video link plays just that video, even when it was opened from a playlist or a mix.
        return _youtube_video(query["v"][0])
    if len(segments) >= 2 and segments[0] in ("shorts", "live", "embed", "v"):
        return _youtube_video(segments[1])
    if parts.path in ("/playlist", "/watch") and _LIST_ID.match(query.get("list", [""])[0]):
        return ParsedQuery(
            SourceKind.YOUTUBE,
            "https://www.youtube.com/playlist?" + urlencode({"list": query["list"][0]}),
        )
    if host == "music.youtube.com" and segments[:1] == ["browse"]:
        raise UnsupportedLink(
            "YouTube Music album pages can't be opened directly. On the album, use "
            "⋮ → Share → Copy link instead: that gives a playlist link I can play."
        )
    if segments[:1] in (["channel"], ["c"], ["user"]) or parts.path.startswith("/@"):
        raise UnsupportedLink("That's a YouTube channel. Send me a video or playlist link instead.")
    raise UnsupportedLink("I can only play YouTube video and playlist links.")


def _parse_spotify(parts: SplitResult) -> ParsedQuery:
    segments = [s for s in parts.path.split("/") if s]
    if segments[:1] and segments[0].startswith("intl-"):  # /intl-de/track/...
        segments = segments[1:]
    if segments[:1] == ["embed"]:
        segments = segments[1:]
    if len(segments) >= 4 and segments[0] == "user" and segments[2] == "playlist":
        segments = segments[2:]  # legacy /user/<name>/playlist/<id>
    if len(segments) >= 2 and segments[0] in _SPOTIFY_TYPES and _SPOTIFY_ID.match(segments[1]):
        kind, spotify_id = segments[0], segments[1]
        return ParsedQuery(SourceKind.SPOTIFY, spotify_url(kind, spotify_id), kind, spotify_id)
    raise UnsupportedLink(
        "I can play Spotify tracks, albums, playlists and artists, but not podcasts or other pages."
    )


def _parse_apple(parts: SplitResult) -> ParsedQuery:
    segments = [s for s in parts.path.split("/") if s]
    # /<country>/<type>/<slug>/<id>, where the country part is optional
    if not any(s in _APPLE_TYPES for s in segments[:2]):
        raise UnsupportedLink(
            "I can play Apple Music songs, albums, playlists and artists, but not radio or videos."
        )
    if segments and re.fullmatch(r"id\d+", segments[-1]):
        segments[-1] = segments[-1][2:]  # old itunes.apple.com links: .../id1440857781
    query = parse_qs(parts.query)
    track = urlencode({"i": query["i"][0]}) if "i" in query else ""
    return ParsedQuery(
        SourceKind.APPLE_MUSIC,
        urlunsplit(("https", "music.apple.com", "/" + "/".join(segments), track, "")),
    )
