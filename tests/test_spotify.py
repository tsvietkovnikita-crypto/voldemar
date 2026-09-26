"""Parsing of real Spotify embed pages saved in tests/fixtures (trimmed to their __NEXT_DATA__)."""

import json
import re
from pathlib import Path

import pytest

from voldemar.music.spotify import PLAYLIST_LIMIT, SpotifyError, parse_embed

FIXTURES = Path(__file__).parent / "fixtures"
SCRIPT = re.compile(r'(<script id="__NEXT_DATA__" type="application/json">)(.*?)(</script>)', re.S)


def fixture(kind: str) -> str:
    return (FIXTURES / f"spotify_{kind}.html").read_text(encoding="utf-8")


def edit_track_list(html: str, edit) -> str:
    match = SCRIPT.search(html)
    data = json.loads(match.group(2))
    edit(data["props"]["pageProps"]["state"]["data"]["entity"]["trackList"])
    return html[: match.start(2)] + json.dumps(data) + html[match.end(2) :]


def test_track() -> None:
    collection = parse_embed(fixture("track"), "track")
    assert collection.name == "Never Gonna Give You Up"
    [track] = collection.tracks
    assert track.title == "Never Gonna Give You Up"
    assert track.artists == "Rick Astley"
    assert track.duration_ms == 213573
    assert track.url == "https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8"
    assert track.artwork and track.artwork.startswith("https://")
    assert track.search_query == "Rick Astley - Never Gonna Give You Up"


def test_album_tracks_share_the_cover() -> None:
    collection = parse_embed(fixture("album"), "album")
    assert collection.name == "Global Warming"
    assert len(collection.tracks) == 18
    first = collection.tracks[0]
    assert first.title == "Global Warming (feat. Sensato)"
    assert first.artists == "Pitbull, Sensato"
    assert first.search_query == "Pitbull - Global Warming (feat. Sensato)"
    assert all(t.artwork == first.artwork for t in collection.tracks)
    assert all(t.duration_ms > 0 and t.url for t in collection.tracks)


def test_playlist() -> None:
    collection = parse_embed(fixture("playlist"), "playlist")
    assert collection.name == "Today\N{RIGHT SINGLE QUOTATION MARK}s Top Hits"
    assert 0 < len(collection.tracks) <= PLAYLIST_LIMIT
    assert all(t.title and t.artists and t.duration_ms > 0 for t in collection.tracks)
    assert all(t.artwork is None for t in collection.tracks)  # the playlist cover isn't the song's


def test_artist_top_tracks() -> None:
    collection = parse_embed(fixture("artist"), "artist")
    assert collection.name == "Pitbull"
    assert len(collection.tracks) == 10
    assert collection.tracks[0].title == "On The Floor"


def test_unplayable_items_and_episodes_are_skipped() -> None:
    def edit(track_list: list[dict]) -> None:
        track_list[0]["isPlayable"] = False
        track_list[1]["entityType"] = "episode"

    tracks = parse_embed(edit_track_list(fixture("album"), edit), "album").tracks
    assert len(tracks) == 16
    assert tracks[0].title != "Global Warming (feat. Sensato)"


def test_playlists_are_capped() -> None:
    html = edit_track_list(fixture("playlist"), lambda tracks: tracks.extend(tracks * 3))
    assert len(parse_embed(html, "playlist").tracks) == PLAYLIST_LIMIT


@pytest.mark.parametrize(
    "html",
    [
        "<html><body>Page not found</body></html>",
        '<script id="__NEXT_DATA__" type="application/json">{not json</script>',
        '<script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>',
    ],
)
def test_unexpected_pages_raise_a_friendly_error(html: str) -> None:
    with pytest.raises(SpotifyError, match="looked different"):
        parse_embed(html, "playlist")


def test_missing_or_private_link() -> None:
    # What Spotify serves (with HTTP 200) for an ID that doesn't exist.
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"status":404,"title":"Page not found"}},"page":"/track/[id]"}'
        "</script>"
    )
    with pytest.raises(SpotifyError, match="doesn't exist"):
        parse_embed(html, "track")


def test_empty_collection_raises() -> None:
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"state":{"data":{"entity":{"name":"x","trackList":[]}}}}}}'
        "</script>"
    )
    with pytest.raises(SpotifyError, match="doesn't contain"):
        parse_embed(html, "playlist")
