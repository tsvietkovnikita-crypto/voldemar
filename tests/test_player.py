"""MusicPlayer logic with Lavalink and Discord replaced by small fakes."""

import asyncio
from types import SimpleNamespace

import pytest
import wavelink

from voldemar.music import player as player_module
from voldemar.music.player import MAX_CONSECUTIVE_FAILURES, MusicPlayer
from voldemar.music.queue import LoopMode, QueueEntry


class FakePlayable:
    def __init__(self, name: str) -> None:
        self.encoded = f"encoded:{name}"
        self.title = name
        self.length = 180_000
        self.artwork = f"https://img/{name}.jpg"
        self.extras: dict = {}


def as_lavalink_sends_it(track: FakePlayable, position: int) -> FakePlayable:
    """The track as it comes back in Lavalink's events: a new object, re-encoded with the
    current playback position (so `encoded` differs), with the userData we sent unchanged."""
    copy = FakePlayable(track.title)
    copy.encoded = f"{track.encoded}@{position}"
    copy.extras = dict(track.extras)
    return copy


def ended(player: MusicPlayer) -> FakePlayable:
    """The track in the end event for the song that's playing now."""
    current = player.tracks.current.playable
    return as_lavalink_sends_it(current, position=current.length)


def entry(name: str, *, pending: bool = False) -> QueueEntry:
    return QueueEntry(
        title=name,
        author="Artist",
        length_ms=180_000,
        requester_id=1,
        source="spotify" if pending else "youtube",
        playable=None if pending else FakePlayable(name),
        search_query=f"Artist - {name}" if pending else None,
    )


def make_player(monkeypatch: pytest.MonkeyPatch, lookups: dict[str, FakePlayable | None]):
    node = SimpleNamespace(
        _inactive_channel_tokens=None, _inactive_player_timeout=None, client=None
    )
    monkeypatch.setattr(wavelink.Pool, "get_node", classmethod(lambda cls, *a: node))

    async def fake_resolve(queue_entry: QueueEntry):
        return lookups.get(queue_entry.title)

    monkeypatch.setattr(player_module.resolver, "resolve", fake_resolve)

    settings = SimpleNamespace(max_queue_size=100, idle_timeout=60, empty_channel_timeout=60)
    client = SimpleNamespace(settings=settings)
    channel = SimpleNamespace(members=[], guild=None)
    player = MusicPlayer(client, channel)
    player._connected = True

    log = SimpleNamespace(played=[], messages=[], stopped=0, left=0)

    async def play(track, **kwargs):
        log.played.append(track.title)
        return track

    async def skip(**kwargs):
        log.stopped += 1

    async def notify(content=None, **kwargs):
        log.messages.append(content)

    async def disconnect(**kwargs):
        player.cleanup()  # like wavelink: disconnecting cleans up...
        await asyncio.sleep(0)  # ...and then still has work to await
        log.left += 1

    player.play, player.skip, player.notify, player.disconnect = play, skip, notify, disconnect
    return player, log


def run(coro):
    return asyncio.run(coro)


def test_starts_when_idle_and_plays_in_order(monkeypatch) -> None:
    async def scenario():
        player, log = make_player(monkeypatch, {})
        player.tracks.add([entry("A"), entry("B")])
        assert await player.start_if_idle() is True
        assert await player.start_if_idle() is False
        await player.on_track_end(ended(player), "finished")
        assert log.played == ["A", "B"]

    run(scenario())


def test_spotify_entries_are_looked_up_before_playing(monkeypatch) -> None:
    async def scenario():
        player, log = make_player(monkeypatch, {"Song": FakePlayable("Song (YouTube)")})
        pending = entry("Song", pending=True)
        player.tracks.add([pending])
        await player.start_if_idle()
        assert log.played == ["Song (YouTube)"]
        assert pending.is_resolved
        assert pending.artwork == "https://img/Song (YouTube).jpg"

    run(scenario())


def test_songs_without_a_match_are_skipped_with_a_message(monkeypatch) -> None:
    async def scenario():
        player, log = make_player(monkeypatch, {"Missing": None})
        player.tracks.add([entry("Missing", pending=True), entry("B")])
        await player.start_if_idle()
        assert log.played == ["B"]
        assert "Couldn't play" in log.messages[0]
        assert player.tracks.history == ()  # the failed entry is dropped, not kept for /previous

    run(scenario())


def test_gives_up_after_too_many_failures_in_a_row(monkeypatch) -> None:
    async def scenario():
        player, log = make_player(monkeypatch, {})
        names = [f"X{i}" for i in range(MAX_CONSECUTIVE_FAILURES + 2)]
        player.tracks.add([entry(n, pending=True) for n in names])
        assert await player.start_if_idle() is False
        assert log.played == []
        assert "in a row failed" in log.messages[-1]
        assert player.tracks.current is None
        assert len(player.tracks.upcoming) == 2  # the rest stays queued for /skip

    run(scenario())


def test_next_song_starts_when_a_song_ends(monkeypatch) -> None:
    """Regression: the end event's track is re-encoded with its end position, so it never
    equals the encoded string that was sent; it's matched by the play ID in userData."""

    async def scenario():
        player, log = make_player(monkeypatch, {})
        player.tracks.add([entry("A"), entry("B"), entry("C")])
        await player.start_if_idle()
        event_track = ended(player)
        assert event_track.encoded != player.tracks.current.playable.encoded
        await player.on_track_end(event_track, "finished")
        await player.on_track_end(ended(player), "finished")
        assert log.played == ["A", "B", "C"]

    run(scenario())


def test_ignores_late_and_self_caused_track_end_events(monkeypatch) -> None:
    async def scenario():
        player, log = make_player(monkeypatch, {})
        # The same song twice: a late event for the first copy must not skip the second.
        first, second, last = entry("A"), entry("A"), entry("C")
        player.tracks.add([first, second, last])
        await player.start_if_idle()
        old = ended(player)
        await player.skip_current()  # user skips to the second "A"
        await player.on_track_end(old, "finished")  # arrives late, belongs to the first "A"
        await player.on_track_end(ended(player), "replaced")
        await player.on_track_end(ended(player), "stopped")
        assert log.played == ["A", "A"]
        assert player.tracks.current is second
        assert player.tracks.upcoming == (last,)

    run(scenario())


def test_load_failure_moves_on(monkeypatch) -> None:
    async def scenario():
        player, log = make_player(monkeypatch, {})
        player.tracks.add([entry("A"), entry("B")])
        await player.start_if_idle()
        player.last_error = "This video is unavailable"
        await player.on_track_end(ended(player), "loadFailed")
        assert log.played == ["A", "B"]
        assert "This video is unavailable" in log.messages[0]

    run(scenario())


def test_loop_track_replays_the_same_song(monkeypatch) -> None:
    async def scenario():
        player, log = make_player(monkeypatch, {})
        player.tracks.add([entry("A"), entry("B")])
        await player.start_if_idle()
        player.tracks.loop = LoopMode.TRACK
        await player.on_track_end(ended(player), "finished")
        assert log.played == ["A", "A"]

    run(scenario())


def test_skipping_the_last_song_stops_the_audio(monkeypatch) -> None:
    async def scenario():
        player, log = make_player(monkeypatch, {})
        player.tracks.add([entry("A")])
        await player.start_if_idle()
        assert await player.skip_current() is None
        assert log.stopped == 1
        assert player.tracks.current is None
        player.cleanup()  # cancel the idle timer that was started

    run(scenario())


def test_auto_leave_finishes_disconnecting(monkeypatch) -> None:
    """The idle timer calls teardown(), whose cleanup() must not cancel the timer itself."""

    async def scenario():
        player, log = make_player(monkeypatch, {})
        player._idle_task = asyncio.create_task(player._leave_later(0, "bye"))
        await player._idle_task
        assert log.left == 1
        assert log.messages == ["bye"]

    run(scenario())


def test_nothing_plays_after_stop(monkeypatch) -> None:
    async def scenario():
        player, log = make_player(monkeypatch, {})
        player.tracks.add([entry("A"), entry("B")])
        await player.start_if_idle()
        await player.teardown()
        assert log.left == 1
        assert player.tracks.current is None and player.tracks.upcoming == ()
        assert await player.start_if_idle() is False
        assert log.played == ["A"]

    run(scenario())


def test_messages_never_exceed_discords_limit(monkeypatch) -> None:
    async def scenario():
        player, _ = make_player(monkeypatch, {})
        sent = []

        class Channel:
            async def send(self, content, **kwargs):
                sent.append(content)

        player.text_channel = Channel()
        await MusicPlayer.notify(player, "⚠️ " + "x" * 5000)  # the real notify, not the fake
        assert len(sent[0]) == 2000

    run(scenario())
