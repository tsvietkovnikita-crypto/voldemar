import random

import pytest

from voldemar.music.queue import LoopMode, QueueEntry, QueueFull, TrackQueue


def make(*titles: str) -> list[QueueEntry]:
    return [
        QueueEntry(title=t, author="a", length_ms=1000, requester_id=1, source="youtube")
        for t in titles
    ]


def titles(entries) -> list[str]:
    return [e.title for e in entries]


def queue_with(*names: str, **kwargs) -> TrackQueue:
    queue = TrackQueue(**kwargs)
    queue.add(make(*names))
    return queue


def test_advance_plays_in_order_and_records_history() -> None:
    q = queue_with("A", "B", "C")
    assert q.advance().title == "A"
    assert q.advance().title == "B"
    assert titles(q.upcoming) == ["C"]
    assert titles(q.history) == ["A"]


def test_advance_returns_none_at_the_end() -> None:
    q = queue_with("A")
    q.advance()
    assert q.advance() is None
    assert q.current is None
    assert titles(q.history) == ["A"]


def test_loop_track_repeats_only_when_finished() -> None:
    q = queue_with("A", "B")
    q.advance()
    q.loop = LoopMode.TRACK
    assert q.advance(finished=True).title == "A"
    assert q.advance(finished=True).title == "A"
    assert q.advance(finished=False).title == "B"  # a skip moves on


def test_loop_queue_recycles_finished_and_skipped_entries() -> None:
    q = queue_with("A", "B")
    q.loop = LoopMode.QUEUE
    order = [q.advance(finished=f).title for f in (False, True, False, True)]
    assert order == ["A", "B", "A", "B"]


def test_loop_queue_with_single_entry_repeats_it() -> None:
    q = queue_with("A")
    q.loop = LoopMode.QUEUE
    q.advance()
    assert q.advance().title == "A"


def test_discard_drops_failed_entry_even_when_looping() -> None:
    q = queue_with("A", "B")
    q.loop = LoopMode.QUEUE
    q.advance()
    assert q.advance(discard=True).title == "B"
    assert titles(q.upcoming) == []
    assert titles(q.history) == []


def test_peek_follows_loop_mode() -> None:
    q = queue_with("A", "B")
    q.advance()
    assert q.peek().title == "B"
    q.loop = LoopMode.TRACK
    assert q.peek().title == "A"
    q.loop = LoopMode.QUEUE
    q.clear()
    assert q.peek().title == "A"
    q.loop = LoopMode.OFF
    assert q.peek() is None


def test_skip_to_drops_entries_in_between() -> None:
    q = queue_with("A", "B", "C", "D")
    q.advance()
    assert q.skip_to(2).title == "C"
    assert titles(q.upcoming) == ["D"]
    assert titles(q.history) == ["A"]


def test_skip_to_keeps_circular_order_when_looping_queue() -> None:
    q = queue_with("A", "B", "C", "D", "E")
    q.loop = LoopMode.QUEUE
    q.advance()  # playing A
    assert q.skip_to(3).title == "D"
    assert titles(q.upcoming) == ["E", "A", "B", "C"]


@pytest.mark.parametrize("position", [0, 3])
def test_skip_to_rejects_bad_positions(position: int) -> None:
    q = queue_with("A", "B")
    with pytest.raises(IndexError):
        q.skip_to(position)


def test_previous_goes_back_and_requeues_current() -> None:
    q = queue_with("A", "B", "C")
    q.advance()
    q.advance()  # playing B
    assert q.previous().title == "A"
    assert titles(q.upcoming) == ["B", "C"]
    assert q.previous() is None


def test_previous_does_not_duplicate_recycled_entry() -> None:
    q = queue_with("A", "B")
    q.loop = LoopMode.QUEUE
    q.advance()
    q.advance()  # playing B, upcoming [A]
    assert q.previous().title == "A"
    assert titles(q.upcoming) == ["B"]


def test_add_respects_max_size() -> None:
    q = TrackQueue(max_size=3)
    assert q.add(make("A", "B")) == 2
    assert q.add(make("C", "D")) == 1
    with pytest.raises(QueueFull):
        q.add(make("E"))


def test_remove_and_move_use_one_based_positions() -> None:
    q = queue_with("A", "B", "C", "D")
    assert q.remove(2).title == "B"
    assert q.move(3, 1).title == "D"
    assert titles(q.upcoming) == ["D", "A", "C"]
    with pytest.raises(IndexError):
        q.remove(4)
    with pytest.raises(IndexError):
        q.move(1, 0)


def test_shuffle_keeps_every_entry() -> None:
    q = queue_with(*"ABCDEFGH")
    q.shuffle(random.Random(1))
    assert sorted(titles(q.upcoming)) == list("ABCDEFGH")
    assert titles(q.upcoming) != list("ABCDEFGH")


def test_same_song_twice_is_two_entries() -> None:
    q = TrackQueue()
    entry = make("A")[0]
    q.add([entry, entry])
    q.remove(1)
    assert len(q.upcoming) == 1


def test_clear_and_reset() -> None:
    q = queue_with("A", "B", "C")
    q.advance()
    q.loop = LoopMode.QUEUE
    assert q.clear() == 2
    assert q.current.title == "A"
    q.reset()
    assert q.current is None
    assert q.history == ()
    assert q.loop is LoopMode.OFF


def test_page_numbers_and_clamping() -> None:
    q = queue_with(*[str(i) for i in range(1, 24)])
    items, pages = q.page(3)
    assert pages == 3
    assert [p for p, _ in items] == [21, 22, 23]
    assert q.page(99)[0][0][0] == 21
    assert TrackQueue().page(1) == ([], 1)


def test_upcoming_length_ignores_streams() -> None:
    q = queue_with("A", "B")
    q.add([QueueEntry("Radio", "a", 0, 1, "twitch", is_stream=True)])
    assert q.upcoming_length_ms() == 2000


def test_loop_mode_cycles() -> None:
    assert [LoopMode.OFF.next(), LoopMode.TRACK.next(), LoopMode.QUEUE.next()] == [
        LoopMode.TRACK,
        LoopMode.QUEUE,
        LoopMode.OFF,
    ]
