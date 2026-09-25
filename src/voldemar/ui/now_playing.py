"""The "Now playing" embed."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from voldemar.music.queue import LoopMode, QueueEntry
from voldemar.ui.formatting import entry_duration, entry_link, progress_bar, source_name

if TYPE_CHECKING:
    from voldemar.music.player import MusicPlayer

EMBED_COLOR = 0x1DB954


def now_playing_embed(
    player: MusicPlayer, entry: QueueEntry, *, show_progress: bool = False
) -> discord.Embed:
    embed = discord.Embed(
        title="Now playing", description=entry_link(entry, 200), color=EMBED_COLOR
    )
    embed.add_field(name="Artist", value=discord.utils.escape_markdown(entry.author) or "—")

    length = player.current.length if player.current is not None else entry.length_ms
    if show_progress and not entry.is_stream:
        embed.add_field(name="Progress", value=progress_bar(player.position, length), inline=False)
    else:
        embed.add_field(name="Duration", value=entry_duration(entry))

    embed.add_field(name="Requested by", value=f"<@{entry.requester_id}>")
    upcoming = player.tracks.peek() if player.tracks.loop is not LoopMode.TRACK else None
    if upcoming is not None and upcoming is not entry:
        embed.add_field(name="Up next", value=entry_link(upcoming, 80), inline=False)

    if entry.artwork:
        embed.set_thumbnail(url=entry.artwork)
    footer = [source_name(entry), f"{len(player.tracks.upcoming)} in queue"]
    if player.tracks.loop is not LoopMode.OFF:
        footer.append(f"loop: {player.tracks.loop.value}")
    if player.paused:
        footer.append("paused")
    embed.set_footer(text=" · ".join(footer))
    return embed
