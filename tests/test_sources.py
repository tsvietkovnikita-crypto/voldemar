import pytest

from voldemar.music.sources import SourceKind, UnsupportedLink, parse_query

RICK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
SPOTIFY_ID = "4PTG3Z6ehGkBFwjybzWkR8"


@pytest.mark.parametrize(
    "link",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ&si=abc",
        "https://youtu.be/dQw4w9WgXcQ?si=share",
        "youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
        "<https://www.youtube.com/watch?v=dQw4w9WgXcQ>",
        # Opened from a mix or a playlist: still just the one video.
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ&start_radio=1",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL0RwveZt5W5Nv9Ux0c36BWutcJHVfzrzY&index=3",
    ],
)
def test_youtube_video_links_normalise_to_one_video(link: str) -> None:
    parsed = parse_query(link)
    assert parsed.kind is SourceKind.YOUTUBE
    assert parsed.value == RICK


@pytest.mark.parametrize(
    "link",
    [
        "https://www.youtube.com/playlist?list=PL0RwveZt5W5Nv9Ux0c36BWutcJHVfzrzY",
        "https://music.youtube.com/playlist?list=PL0RwveZt5W5Nv9Ux0c36BWutcJHVfzrzY&si=x",
        "https://www.youtube.com/watch?list=PL0RwveZt5W5Nv9Ux0c36BWutcJHVfzrzY",
    ],
)
def test_youtube_playlist_links(link: str) -> None:
    parsed = parse_query(link)
    assert parsed.kind is SourceKind.YOUTUBE
    assert (
        parsed.value == "https://www.youtube.com/playlist?list=PL0RwveZt5W5Nv9Ux0c36BWutcJHVfzrzY"
    )


@pytest.mark.parametrize(
    ("link", "message"),
    [
        ("https://music.youtube.com/browse/MPREb_abc123", "Share"),
        ("https://www.youtube.com/@RickAstleyYT", "channel"),
        ("https://www.youtube.com/feed/trending", "video and playlist"),
    ],
)
def test_unplayable_youtube_links_explain_why(link: str, message: str) -> None:
    with pytest.raises(UnsupportedLink, match=message):
        parse_query(link)


@pytest.mark.parametrize(
    ("link", "kind"),
    [
        (f"https://open.spotify.com/track/{SPOTIFY_ID}", "track"),
        (f"https://open.spotify.com/track/{SPOTIFY_ID}?si=abcdef", "track"),
        (f"https://open.spotify.com/intl-de/track/{SPOTIFY_ID}", "track"),
        (f"https://open.spotify.com/embed/album/{SPOTIFY_ID}", "album"),
        (f"https://open.spotify.com/playlist/{SPOTIFY_ID}", "playlist"),
        (f"https://open.spotify.com/user/someone/playlist/{SPOTIFY_ID}", "playlist"),
        (f"https://open.spotify.com/artist/{SPOTIFY_ID}", "artist"),
        (f"spotify:track:{SPOTIFY_ID}", "track"),
        (f"spotify:user:someone:playlist:{SPOTIFY_ID}", "playlist"),
    ],
)
def test_spotify_links(link: str, kind: str) -> None:
    parsed = parse_query(link)
    assert parsed.kind is SourceKind.SPOTIFY
    assert (parsed.spotify_type, parsed.spotify_id) == (kind, SPOTIFY_ID)
    assert parsed.value == f"https://open.spotify.com/{kind}/{SPOTIFY_ID}"
    assert not parsed.is_spotify_short_link


def test_spotify_short_link_is_resolved_later() -> None:
    parsed = parse_query("https://spotify.link/AbCdEfGh123")
    assert parsed.kind is SourceKind.SPOTIFY
    assert parsed.is_spotify_short_link


def test_spotify_podcasts_are_rejected() -> None:
    with pytest.raises(UnsupportedLink, match="podcasts"):
        parse_query(f"https://open.spotify.com/episode/{SPOTIFY_ID}")


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        (
            "https://music.apple.com/us/album/never-gonna-give-you-up/1773292758?i=1773293184",
            "https://music.apple.com/us/album/never-gonna-give-you-up/1773292758?i=1773293184",
        ),
        (
            "https://geo.music.apple.com/us/album/x/1773292758?i=1773293184&ls=1&app=music",
            "https://music.apple.com/us/album/x/1773292758?i=1773293184",
        ),
        (
            "https://music.apple.com/gb/song/never-gonna-give-you-up/1773293184",
            "https://music.apple.com/gb/song/never-gonna-give-you-up/1773293184",
        ),
        (
            "https://music.apple.com/us/playlist/todays-hits/pl.f4d106fed2bd41149aaacabb233eb5eb",
            "https://music.apple.com/us/playlist/todays-hits/pl.f4d106fed2bd41149aaacabb233eb5eb",
        ),
        (
            "https://itunes.apple.com/us/album/whenever-you-need-somebody/id1773292758",
            "https://music.apple.com/us/album/whenever-you-need-somebody/1773292758",
        ),
    ],
)
def test_apple_music_links_are_normalised(link: str, expected: str) -> None:
    parsed = parse_query(link)
    assert parsed.kind is SourceKind.APPLE_MUSIC
    assert parsed.value == expected


def test_apple_music_radio_is_rejected() -> None:
    with pytest.raises(UnsupportedLink, match="radio"):
        parse_query("https://music.apple.com/us/station/rick-astley-radio/ra.123")


def test_other_links_pass_through() -> None:
    link = "https://soundcloud.com/rick-astley-official/never-gonna-give-you-up"
    assert parse_query(link).kind is SourceKind.OTHER_URL
    assert parse_query(link).value == link


@pytest.mark.parametrize("text", ["never gonna give you up", "Кино — Группа крови", "a.b"])
def test_plain_text_is_a_search(text: str) -> None:
    parsed = parse_query(f"  {text} ")
    assert parsed.kind is SourceKind.SEARCH
    assert parsed.value == text


def test_empty_and_overlong_input_is_rejected() -> None:
    with pytest.raises(UnsupportedLink):
        parse_query("   ")
    with pytest.raises(UnsupportedLink, match="too long"):
        parse_query("x " * 150)
