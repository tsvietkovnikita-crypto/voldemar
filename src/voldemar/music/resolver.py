"""Turn /play input into queue entries, and find YouTube Music audio for Spotify songs."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

import aiohttp
import wavelink

from voldemar.music import spotify
from voldemar.music.queue import QueueEntry
from voldemar.music.sources import ParsedQuery, SourceKind, UnsupportedLink, parse_query

log = logging.getLogger(__name__)

SEARCH_PREFIXES = ("ytmsearch", "ytsearch")  # YouTube Music first: official audio, not videos
GOOD_MATCH = 5.0  # a score this high on YouTube Music makes the plain YouTube search unnecessary


class LoadError(Exception):
    """Nothing playable was found. The message is shown to the user."""


@dataclass(slots=True)
class LoadResult:
    entries: list[QueueEntry]
    collection: str | None = None  # playlist, album or artist name; None for a single song
    note: str | None = None  # extra information for the user, e.g. Spotify's 100-song limit


def entry_from_playable(track: wavelink.Playable, requester_id: int) -> QueueEntry:
    return QueueEntry(
        title=track.title,
        author=track.author,
        length_ms=track.length,
        requester_id=requester_id,
        source=track.source,
        uri=track.uri,
        artwork=track.artwork,
        is_stream=track.is_stream,
        playable=track,
    )


def entry_from_spotify(track: spotify.SpotifyTrack, requester_id: int) -> QueueEntry:
    return QueueEntry(
        title=track.title,
        author=track.artists,
        length_ms=track.duration_ms,
        requester_id=requester_id,
        source="spotify",
        uri=track.url,
        artwork=track.artwork,
        search_query=track.search_query,
    )


async def load(query: str, requester_id: int, session: aiohttp.ClientSession) -> LoadResult:
    try:
        parsed = parse_query(query)
    except UnsupportedLink as e:
        raise LoadError(str(e)) from None

    if parsed.kind is SourceKind.SPOTIFY:
        return await _load_spotify(parsed, requester_id, session)
    if parsed.kind is SourceKind.SEARCH:
        return await _load_search(parsed.value, requester_id)
    return await _load_url(parsed, requester_id)


async def _fetch(identifier: str) -> list[wavelink.Playable] | wavelink.Playlist:
    try:
        return await wavelink.Pool.fetch_tracks(identifier)
    except wavelink.LavalinkLoadException as e:
        log.warning("Lavalink failed to load %r: %s (cause: %s)", identifier, e.error, e.cause)
        raise LoadError(f"Couldn't load that: {e.error}") from e
    except wavelink.InvalidNodeException:
        raise LoadError(
            "The music server isn't connected yet. Try again in a few seconds."
        ) from None


async def _load_url(parsed: ParsedQuery, requester_id: int) -> LoadResult:
    result = await _fetch(parsed.value)
    if isinstance(result, wavelink.Playlist):
        entries = [entry_from_playable(t, requester_id) for t in result.tracks]
        if not entries:
            raise LoadError("That playlist is empty.")
        return LoadResult(entries, collection=result.name)
    if not result:
        raise LoadError(_not_found_message(parsed.kind))
    return LoadResult([entry_from_playable(result[0], requester_id)])


def _not_found_message(kind: SourceKind) -> str:
    if kind is SourceKind.YOUTUBE:
        return "YouTube couldn't find that. It may be private, deleted or blocked in this country."
    if kind is SourceKind.APPLE_MUSIC:
        return "Apple Music couldn't find that. It may not be available in this country."
    return (
        "I can't play that link. Try YouTube, YouTube Music, Spotify, Apple Music, SoundCloud, "
        "Bandcamp, Twitch or Vimeo, or just type a song name."
    )


async def _load_search(text: str, requester_id: int) -> LoadResult:
    for prefix in SEARCH_PREFIXES:
        result = await _fetch(f"{prefix}:{text}")
        tracks = result.tracks if isinstance(result, wavelink.Playlist) else result
        if tracks:
            return LoadResult([entry_from_playable(tracks[0], requester_id)])
    raise LoadError(f"Nothing found for “{text}”.")


async def _load_spotify(
    parsed: ParsedQuery, requester_id: int, session: aiohttp.ClientSession
) -> LoadResult:
    try:
        if parsed.is_spotify_short_link:
            parsed = parse_query(await spotify.expand_short_link(session, parsed.value))
        assert parsed.spotify_type is not None and parsed.spotify_id is not None
        collection = await spotify.fetch_collection(session, parsed.spotify_type, parsed.spotify_id)
    except (spotify.SpotifyError, UnsupportedLink) as e:
        raise LoadError(str(e)) from None

    entries = [entry_from_spotify(t, requester_id) for t in collection.tracks]
    note = None
    if collection.kind == "playlist" and len(entries) >= spotify.PLAYLIST_LIMIT:
        note = "Spotify only shares the first 100 songs of a playlist."
    name = None if collection.kind == "track" else collection.name
    return LoadResult(entries, collection=name, note=note)


async def resolve(entry: QueueEntry) -> wavelink.Playable | None:
    """Find audio for a Spotify entry: the best YouTube Music match, else the best YouTube match."""
    target = Candidate(entry.title, entry.author, entry.length_ms)
    best: tuple[float, wavelink.Playable] | None = None
    for prefix in SEARCH_PREFIXES:
        try:
            result = await wavelink.Pool.fetch_tracks(f"{prefix}:{entry.search_query}")
        except wavelink.InvalidNodeException:
            return None
        except wavelink.LavalinkLoadException as e:
            log.warning("Search for %r failed: %s", entry.search_query, e.error)
            continue
        tracks = (result.tracks if isinstance(result, wavelink.Playlist) else result)[:10]
        found = best_match(target, [Candidate(t.title, t.author, t.length) for t in tracks])
        if found is None:
            continue
        index, score = found
        if best is None or score > best[0]:
            best = (score, tracks[index])
        if score >= GOOD_MATCH:
            break
    if best is None:
        log.info("No match for %r", entry.search_query)
        return None
    log.debug("Matched %r to %r (score %.1f)", entry.search_query, best[1].title, best[0])
    return best[1]


# --- Match scoring (pure functions, unit-tested) ---------------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    title: str
    author: str  # for the target: comma-separated artists
    length_ms: int


# Words that mark a different recording than the one on Spotify, unless the Spotify title has them.
_VERSION_WORDS = (
    "live",
    "cover",
    "karaoke",
    "instrumental",
    "remix",
    "acoustic",
    "sped up",
    "slowed",
    "nightcore",
    "8d",
    "reverb",
    "extended",
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", text).strip()


def _squash(text: str) -> str:
    return _normalize(text).replace(" ", "")


def _base_title(title: str) -> str:
    """The title without "(feat. ...)", "[Remastered]" or " - Radio Edit" style additions."""
    title = re.sub(r"[(\[][^)\]]*[)\]]", " ", title)
    return _normalize(title.split(" - ")[0])


_TOPIC_SUFFIX = re.compile(r"\s*-\s*Topic$")  # YouTube's auto-generated "official audio" channels


def _channel_name(author: str) -> str:
    author = _TOPIC_SUFFIX.sub("", author.strip())
    return _squash(re.sub(r"VEVO$", "", author))


def score(target: Candidate, candidate: Candidate) -> float:
    total = 0.0
    title = _normalize(candidate.title)

    base = _base_title(target.title)
    if base and base in title:
        total += 2

    artists = [_squash(a) for a in target.author.split(",") if _squash(a)]
    channel = _channel_name(candidate.author)
    if artists:
        if channel == artists[0]:
            total += 3
        elif any(a == channel or a in _squash(candidate.title) for a in artists):
            total += 2
    if _TOPIC_SUFFIX.search(candidate.author):
        total += 1  # the plain album audio beats a music video with an intro or outro

    if target.length_ms > 0 and candidate.length_ms > 0:
        difference = abs(target.length_ms - candidate.length_ms)
        if difference <= 3_000:
            total += 3
        elif difference <= 10_000:
            total += 1
        elif difference > 30_000:
            total -= 3

    target_title = _normalize(target.title)
    for word in _VERSION_WORDS:
        pattern = rf"\b{word}\b"
        if re.search(pattern, title) and not re.search(pattern, target_title):
            total -= 3
            break
    return total


def best_match(target: Candidate, candidates: Sequence[Candidate]) -> tuple[int, float] | None:
    """Index and score of the best candidate; earlier (higher-ranked) results win ties."""
    if not candidates:
        return None
    scores = [score(target, c) for c in candidates]
    index = max(range(len(candidates)), key=lambda i: (scores[i], -i))
    return index, scores[index]
