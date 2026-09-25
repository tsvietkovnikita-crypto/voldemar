"""Spotify links to song metadata, read from Spotify's public embed widget (no API key needed).

Since February 2026 Spotify's Web API no longer serves other people's playlists to development
apps, but the embed page at open.spotify.com/embed/<type>/<id> still carries title, artists and
duration in its __NEXT_DATA__ JSON: for a track, an album, a playlist (first 100 songs) or an
artist's top tracks. The songs are then played from YouTube Music, looked up just before each plays.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

EMBED_URL = "https://open.spotify.com/embed/{kind}/{id}"
PLAYLIST_LIMIT = 100  # Spotify's embed never includes more
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
_TIMEOUT = aiohttp.ClientTimeout(total=15)
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_FULL_LINK = re.compile(
    r"https://open\.spotify\.com/(?:intl-[a-z-]+/)?(?:track|album|playlist|artist)/[A-Za-z0-9]{22}"
)


class SpotifyError(Exception):
    """Spotify metadata couldn't be read. The message is shown to the user."""


@dataclass(frozen=True, slots=True)
class SpotifyTrack:
    title: str
    artists: str  # "Artist A, Artist B"
    duration_ms: int
    url: str | None
    artwork: str | None = None

    @property
    def search_query(self) -> str:
        primary = self.artists.split(",")[0].strip()
        return f"{primary} - {self.title}" if primary else self.title


@dataclass(frozen=True, slots=True)
class SpotifyCollection:
    kind: str  # track, album, playlist or artist
    name: str
    tracks: list[SpotifyTrack]


def _clean(text: object) -> str:
    """Collapse whitespace; Spotify separates artists with non-breaking spaces."""
    return " ".join(str(text or "").split())


def _track_url(uri: object) -> str | None:
    if isinstance(uri, str) and uri.startswith("spotify:track:"):
        return "https://open.spotify.com/track/" + uri.removeprefix("spotify:track:")
    return None


def _artwork(entity: dict[str, Any]) -> str | None:
    """The image closest to 300 px wide, a good size for embed thumbnails."""
    images = (entity.get("visualIdentity") or {}).get("image") or []
    images = [i for i in images if isinstance(i, dict) and i.get("url")]
    if not images:
        return None
    return min(images, key=lambda i: abs((i.get("maxWidth") or 300) - 300))["url"]


def parse_embed(html: str, kind: str) -> SpotifyCollection:
    unreadable = SpotifyError(
        "Spotify's page looked different than expected, so I couldn't read it."
    )
    match = _NEXT_DATA.search(html)
    if match is None:
        raise unreadable
    try:
        page = json.loads(match.group(1))["props"]["pageProps"]
        if page.get("status") in (400, 404):  # missing or private: still HTTP 200
            raise SpotifyError("Spotify says that link doesn't exist, or it's private.")
        entity = page["state"]["data"]["entity"]
    except (ValueError, KeyError, TypeError):
        raise unreadable from None

    name = _clean(entity.get("name") or entity.get("title")) or "Spotify"
    artwork = _artwork(entity)

    if kind == "track":
        names = (_clean(artist.get("name")) for artist in entity.get("artists") or [])
        tracks = [
            SpotifyTrack(
                title=_clean(entity.get("title")) or name,
                artists=", ".join(n for n in names if n),
                duration_ms=int(entity.get("duration") or 0),
                url=_track_url(entity.get("uri")),
                artwork=artwork,
            )
        ]
    else:
        # Album covers belong to every song; playlist and artist images don't.
        cover = artwork if kind == "album" else None
        tracks = [
            SpotifyTrack(
                title=_clean(item["title"]),
                artists=_clean(item.get("subtitle")),
                duration_ms=int(item.get("duration") or 0),
                url=_track_url(item.get("uri")),
                artwork=cover,
            )
            for item in entity.get("trackList") or []
            if item.get("title")
            and item.get("isPlayable", True)
            and item.get("entityType", "track") == "track"  # skip podcast episodes in playlists
        ]

    if not tracks:
        raise SpotifyError("That Spotify link doesn't contain any playable songs.")
    return SpotifyCollection(kind=kind, name=name, tracks=tracks[:PLAYLIST_LIMIT])


async def fetch_collection(
    session: aiohttp.ClientSession, kind: str, spotify_id: str
) -> SpotifyCollection:
    url = EMBED_URL.format(kind=kind, id=spotify_id)
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT) as resp:
            if resp.status in (400, 404):
                raise SpotifyError("Spotify says that link doesn't exist, or it's private.")
            if resp.status != 200:
                raise SpotifyError(
                    f"Spotify answered with an error ({resp.status}). Try again soon."
                )
            html = await resp.text()
    except (aiohttp.ClientError, TimeoutError) as e:
        raise SpotifyError("Couldn't reach Spotify. Try again in a moment.") from e
    return parse_embed(html, kind)


async def expand_short_link(session: aiohttp.ClientSession, url: str) -> str:
    """Turn a spotify.link/... share link into the open.spotify.com link it points to."""
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT) as resp:
            final_url = str(resp.url)
            body = await resp.text() if resp.status == 200 else ""
    except (aiohttp.ClientError, TimeoutError) as e:
        raise SpotifyError("Couldn't reach Spotify. Try again in a moment.") from e

    # Usually a plain redirect; sometimes an HTML page that links to the target.
    for candidate in (final_url, body):
        if match := _FULL_LINK.search(candidate):
            return match.group(0)
    raise SpotifyError(
        "Couldn't open that spotify.link short link. Paste the full open.spotify.com link instead."
    )
