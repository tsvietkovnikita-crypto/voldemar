"""The play queue, owned by the bot rather than wavelink.

This module deliberately imports neither discord.py nor wavelink, so the queue rules (loop modes,
history, skipping, reordering) can be unit-tested on their own.
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class LoopMode(Enum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"

    def next(self) -> LoopMode:
        """The mode after this one, for a button that cycles off -> track -> queue -> off."""
        modes = list(LoopMode)
        return modes[(modes.index(self) + 1) % len(modes)]


class QueueFull(Exception):
    pass


@dataclass(eq=False)  # identity equality: the same song queued twice is two separate entries
class QueueEntry:
    title: str
    author: str
    length_ms: int
    requester_id: int
    source: str  # where the link came from: "youtube", "spotify", "applemusic", "soundcloud", ...
    uri: str | None = None
    artwork: str | None = None
    is_stream: bool = False
    # The wavelink.Playable to send to Lavalink. None means the entry still has to be looked up
    # (Spotify metadata); `search_query` is used for that.
    playable: Any = None
    search_query: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.playable is not None


class TrackQueue:
    """The current entry, the upcoming entries and recently played history."""

    def __init__(self, *, max_size: int = 500, history_size: int = 50) -> None:
        self.max_size = max_size
        self.loop = LoopMode.OFF
        self.current: QueueEntry | None = None
        self._upcoming: list[QueueEntry] = []
        self._history: deque[QueueEntry] = deque(maxlen=history_size)

    @property
    def upcoming(self) -> tuple[QueueEntry, ...]:
        return tuple(self._upcoming)

    @property
    def history(self) -> tuple[QueueEntry, ...]:
        return tuple(self._history)

    @property
    def free_slots(self) -> int:
        return max(self.max_size - len(self._upcoming), 0)

    def peek(self) -> QueueEntry | None:
        """The entry that plays after the current one finishes, if any."""
        if self.loop is LoopMode.TRACK:
            return self.current
        if self._upcoming:
            return self._upcoming[0]
        if self.loop is LoopMode.QUEUE:
            return self.current
        return None

    def upcoming_length_ms(self) -> int:
        return sum(e.length_ms for e in self._upcoming if not e.is_stream)

    def add(self, entries: Iterable[QueueEntry]) -> int:
        """Append entries up to `max_size`; returns how many were added."""
        room = self.free_slots
        if room == 0:
            raise QueueFull
        accepted = list(entries)[:room]
        self._upcoming.extend(accepted)
        return len(accepted)

    def advance(self, *, finished: bool = True, discard: bool = False) -> QueueEntry | None:
        """Move on to the next entry and return it (it becomes `current`); None if nothing is left.

        `finished`: the current track played to the end, so loop-track replays it. Skips pass False.
        `discard`: the current entry failed to play; drop it instead of keeping it in history/loop.
        """
        previous = self.current
        if previous is not None and not discard:
            if finished and self.loop is LoopMode.TRACK:
                return previous
            self._history.append(previous)
            if self.loop is LoopMode.QUEUE:
                self._upcoming.append(previous)
        self.current = self._upcoming.pop(0) if self._upcoming else None
        return self.current

    def skip_to(self, position: int) -> QueueEntry:
        """Jump to the 1-based upcoming `position`. Skipped entries are dropped, or rotated to the
        back when looping the whole queue."""
        self._check_position(position)
        skipped = self._upcoming[: position - 1]
        del self._upcoming[: position - 1]
        if self.loop is LoopMode.QUEUE:
            if self.current is not None:
                self._history.append(self.current)
                self._upcoming.append(self.current)
            self._upcoming.extend(skipped)
            self.current = self._upcoming.pop(0)
            return self.current
        entry = self.advance(finished=False)
        assert entry is not None
        return entry

    def previous(self) -> QueueEntry | None:
        """Step back to the last played entry; the current one returns to the front of the queue."""
        if not self._history:
            return None
        entry = self._history.pop()
        # With loop-queue the entry was also recycled to the back; don't keep a duplicate.
        if self.loop is LoopMode.QUEUE and self._upcoming and self._upcoming[-1] is entry:
            self._upcoming.pop()
        if self.current is not None:
            self._upcoming.insert(0, self.current)
        self.current = entry
        return entry

    def remove(self, position: int) -> QueueEntry:
        self._check_position(position)
        return self._upcoming.pop(position - 1)

    def move(self, source: int, destination: int) -> QueueEntry:
        self._check_position(source)
        self._check_position(destination)
        entry = self._upcoming.pop(source - 1)
        self._upcoming.insert(destination - 1, entry)
        return entry

    def shuffle(self, rng: random.Random | None = None) -> None:
        (rng or random).shuffle(self._upcoming)

    def clear(self) -> int:
        """Remove all upcoming entries (the current one keeps playing); returns how many."""
        count = len(self._upcoming)
        self._upcoming.clear()
        return count

    def reset(self) -> None:
        self.clear()
        self._history.clear()
        self.current = None
        self.loop = LoopMode.OFF

    def page(self, number: int, per_page: int = 10) -> tuple[list[tuple[int, QueueEntry]], int]:
        """Upcoming entries on 1-based page `number` as (position, entry) pairs, and the page count.
        Out-of-range page numbers are clamped."""
        pages = max((len(self._upcoming) + per_page - 1) // per_page, 1)
        number = min(max(number, 1), pages)
        start = (number - 1) * per_page
        items = list(enumerate(self._upcoming[start : start + per_page], start=start + 1))
        return items, pages

    def _check_position(self, position: int) -> None:
        if not 1 <= position <= len(self._upcoming):
            raise IndexError(position)
