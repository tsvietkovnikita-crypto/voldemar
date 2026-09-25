"""The per-server player: wavelink's Player, driven by our own TrackQueue."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

import discord
import wavelink

from voldemar.music import resolver
from voldemar.music.queue import QueueEntry, TrackQueue
from voldemar.ui.formatting import entry_link
from voldemar.ui.now_playing import now_playing_embed

if TYPE_CHECKING:
    from voldemar.bot import VoldemarBot

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 5
NO_MENTIONS = discord.AllowedMentions.none()


class MusicPlayer(wavelink.Player):
    """Plays the entries in `self.tracks`; wavelink's own queue and autoplay stay unused.

    Every change of the current track goes through `_lock`, so a song ending on its own and a
    user pressing skip at the same moment can't advance the queue twice.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.autoplay = wavelink.AutoPlayMode.disabled
        self.tracks = TrackQueue(max_size=self.bot.settings.max_queue_size)
        self.text_channel: discord.abc.Messageable | None = None
        self.last_error: str | None = None  # set by track exception events
        self._lock = asyncio.Lock()
        self._closed = False
        self._failures = 0
        self._prefetch: tuple[QueueEntry, asyncio.Task[wavelink.Playable | None]] | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._empty_task: asyncio.Task[None] | None = None

    @property
    def bot(self) -> VoldemarBot:
        return self.client  # type: ignore[return-value]

    @property
    def can_move(self) -> bool:
        """Whether someone in another channel may take the bot: it's idle or alone."""
        alone = not any(not m.bot for m in getattr(self.channel, "members", []))
        return self.tracks.current is None or alone

    # --- Playback control (all serialised by the lock) ---------------------------------------

    async def start_if_idle(self) -> bool:
        """Start the next entry when nothing is playing. True if something started."""
        async with self._lock:
            if self.tracks.current is not None:
                return False
            return await self._start(self.tracks.advance(finished=False)) is not None

    async def skip_current(self) -> QueueEntry | None:
        """Play the next entry, or stop if there is none. Returns the new current entry."""
        async with self._lock:
            entry = await self._start(self.tracks.advance(finished=False))
            if entry is None and self.connected:
                await self.skip(force=True)  # nothing left: stop the audio
            return entry

    async def skip_to(self, position: int) -> QueueEntry | None:
        async with self._lock:
            return await self._start(self.tracks.skip_to(position))

    async def play_previous(self) -> QueueEntry | None:
        """Go back one track; None if there is no history."""
        async with self._lock:
            entry = self.tracks.previous()
            return await self._start(entry) if entry is not None else None

    async def teardown(self) -> None:
        """Stop, forget the queue and leave the voice channel."""
        self.tracks.reset()
        await self.disconnect()

    # --- Lavalink events, forwarded by cogs/events.py --------------------------------------------

    async def on_track_start(self) -> None:
        self._failures = 0
        self.last_error = None
        self._cancel(self._idle_task)
        self._prefetch_next()
        current = self.tracks.current
        if current is not None:
            await self.notify(embed=now_playing_embed(self, current))

    async def on_track_end(self, track: wavelink.Playable, reason: str) -> None:
        # "replaced", "stopped" and "cleanup" come from our own play/skip/disconnect calls.
        if reason not in ("finished", "loadFailed"):
            return
        async with self._lock:
            entry = self.tracks.current
            if entry is None or entry.playable is None or entry.playable.encoded != track.encoded:
                return  # a late event for a track we already moved past
            error, self.last_error = self.last_error, None
            if reason == "loadFailed":
                if await self._record_failure(entry, error or "it failed to load"):
                    await self._start(self.tracks.advance(finished=False, discard=True))
                return
            if error:
                await self.notify(f"⚠️ {entry_link(entry)} stopped early: {error}")
            await self._start(self.tracks.advance(finished=True))

    def check_listeners(self) -> None:
        """Leave after a while when nobody but bots is left in the voice channel."""
        members = getattr(self.channel, "members", [])
        if any(not m.bot for m in members):
            self._cancel(self._empty_task)
            self._empty_task = None
        elif self._empty_task is None or self._empty_task.done():
            self._empty_task = asyncio.create_task(
                self._leave_later(
                    self.bot.settings.empty_channel_timeout,
                    "Everyone left the voice channel, so I stopped the music. 👋",
                    only_if_empty=True,
                )
            )

    # --- Internals ---------------------------------------------------------------------------

    async def _start(self, entry: QueueEntry | None) -> QueueEntry | None:
        """Play `entry` (already current in the queue), moving past entries that fail.
        Must be called with the lock held."""
        while entry is not None and not self._closed:
            playable = await self._resolve(entry)
            reason = "no matching song found on YouTube"
            if playable is not None and self._closed:
                return None
            if playable is not None:
                try:
                    await self.play(playable, add_history=False)
                    return entry
                except wavelink.LavalinkException as e:
                    reason = e.error or "the music server refused it"
            log.warning("Couldn't play %r: %s", entry.title, reason)
            if not await self._record_failure(entry, reason):
                return None
            entry = self.tracks.advance(finished=False, discard=True)

        if not self._closed:
            self._cancel(self._idle_task)
            self._idle_task = asyncio.create_task(
                self._leave_later(
                    self.bot.settings.idle_timeout,
                    "Nothing was playing, so I left the voice channel. 👋",
                )
            )
        return None

    async def _record_failure(self, entry: QueueEntry, reason: str) -> bool:
        """Report a song that couldn't play. False when too many failed in a row: then we stop
        trying, since the source is probably broken (e.g. YouTube blocking playback)."""
        self._failures += 1
        if self._failures < MAX_CONSECUTIVE_FAILURES:
            await self.notify(f"⚠️ Couldn't play {entry_link(entry)} ({reason}), skipping it.")
            return True
        self._failures = 0
        self.tracks.current = None
        await self.notify(
            f"⚠️ {MAX_CONSECUTIVE_FAILURES} songs in a row failed to play, so I stopped. "
            "YouTube may be blocking playback right now (details in logs/lavalink.log). "
            "Use /skip to try the next song."
        )
        return False

    async def _resolve(self, entry: QueueEntry) -> wavelink.Playable | None:
        """The entry's playable track, looking Spotify songs up on YouTube Music if needed."""
        if entry.playable is not None:
            return entry.playable
        task = None
        if self._prefetch is not None and self._prefetch[0] is entry:
            task = self._prefetch[1]
            self._prefetch = None
        try:
            playable = await task if task is not None else await resolver.resolve(entry)
        except Exception:
            log.exception("Looking up %r failed", entry.search_query)
            return None
        self._apply(entry, playable)
        return playable

    def _prefetch_next(self) -> None:
        """Look up the next Spotify song in the background so it starts without a gap."""
        entry = self.tracks.peek()
        if entry is None or entry.is_resolved:
            return
        if self._prefetch is not None and self._prefetch[0] is entry:
            return

        async def lookup() -> wavelink.Playable | None:
            playable = await resolver.resolve(entry)
            self._apply(entry, playable)
            return playable

        self._prefetch = (entry, asyncio.create_task(lookup()))

    @staticmethod
    def _apply(entry: QueueEntry, playable: wavelink.Playable | None) -> None:
        if playable is not None and entry.playable is None:
            entry.playable = playable
            entry.artwork = entry.artwork or playable.artwork

    async def _leave_later(
        self, delay: float, message: str, *, only_if_empty: bool = False
    ) -> None:
        await asyncio.sleep(delay)
        if self._closed:
            return
        if only_if_empty and any(not m.bot for m in getattr(self.channel, "members", [])):
            return
        if not only_if_empty and self.tracks.current is not None:
            return
        await self.notify(message)
        await self.teardown()

    async def notify(
        self, content: str | None = None, *, embed: discord.Embed | None = None
    ) -> None:
        if self.text_channel is None:
            return
        try:
            await self.text_channel.send(content, embed=embed, allowed_mentions=NO_MENTIONS)
        except discord.HTTPException as e:
            log.warning("Couldn't send a message to the text channel: %s", e)

    @staticmethod
    def _cancel(task: asyncio.Task[Any] | None) -> None:
        if task is not None and not task.done():
            task.cancel()

    def cleanup(self) -> None:
        # Runs on every way of leaving voice: /stop, auto-leave, being kicked, shutdown.
        self._closed = True
        self._cancel(self._idle_task)
        self._cancel(self._empty_task)
        if self._prefetch is not None:
            self._cancel(self._prefetch[1])
            self._prefetch = None
        with contextlib.suppress(KeyError, AttributeError):
            super().cleanup()
