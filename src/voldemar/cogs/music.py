"""Slash commands."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from voldemar.music import resolver
from voldemar.music.guards import GuardError, check_can_join, get_player, join, require_player
from voldemar.music.player import MusicPlayer
from voldemar.music.queue import LoopMode, QueueFull
from voldemar.ui.formatting import (
    entry_duration,
    entry_line,
    entry_link,
    format_duration,
    parse_time,
)
from voldemar.ui.now_playing import EMBED_COLOR, now_playing_embed

if TYPE_CHECKING:
    from voldemar.bot import VoldemarBot

log = logging.getLogger(__name__)

NO_MENTIONS = discord.AllowedMentions.none()
LOOP_LABELS = {LoopMode.OFF: "off", LoopMode.TRACK: "current song", LoopMode.QUEUE: "whole queue"}

HELP_TEXT = """\
**Playback**
`/play query` — a link or search text; joins your voice channel
`/pause` · `/resume` · `/stop` (clears the queue and leaves)
`/skip [to]` — skip, or jump to a queue position · `/previous`
`/seek position` — e.g. `1:23` · `/volume [level]` — 0 to 150

**Queue**
`/queue [page]` · `/nowplaying`
`/loop mode` — off, current song or whole queue · `/shuffle` · `/clear`
`/remove position` · `/move from to`

**Supported links**
YouTube and YouTube Music (videos and playlists), Spotify and Apple Music (songs, albums, \
playlists, artists), SoundCloud, Bandcamp, Twitch and Vimeo. Anything else is searched on \
YouTube Music. Spotify playlists load their first 100 songs.
"""


def songs(count: int) -> str:
    return f"{count} song" if count == 1 else f"{count} songs"


async def reply(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    ephemeral: bool = False,
) -> None:
    """Respond or follow up, without pinging anyone or unfurling links."""
    kwargs: dict[str, Any] = {"allowed_mentions": NO_MENTIONS, "ephemeral": ephemeral}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    else:
        kwargs["suppress_embeds"] = True
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


async def reply_error(interaction: discord.Interaction, message: str) -> None:
    """Show an error only to the user; replaces a public "thinking…" placeholder if there is one."""
    if interaction.response.type is discord.InteractionResponseType.deferred_channel_message:
        with contextlib.suppress(discord.HTTPException):
            await interaction.delete_original_response()
    await reply(interaction, f"❌ {message}", ephemeral=True)


def queue_embed(player: MusicPlayer, page: int) -> discord.Embed:
    tracks = player.tracks
    lines: list[str] = []
    if (current := tracks.current) is not None:
        if current.is_stream:
            timing = "LIVE"
        else:
            length = player.current.length if player.current else current.length_ms
            timing = f"{format_duration(player.position)} / {format_duration(length)}"
        state = "⏸️" if player.paused else "▶️"
        lines.append(f"{state} {entry_link(current)} — `{timing}`")
    items, pages = tracks.page(page)
    if items:
        lines.append("\n**Up next**")
        lines.extend(f"`{number}.` {entry_line(entry)}" for number, entry in items)
    elif tracks.current is not None:
        lines.append("\nNothing queued after this song.")

    footer = [f"Page {min(max(page, 1), pages)}/{pages}", songs(len(tracks.upcoming))]
    if tracks.upcoming:
        footer.append(f"{format_duration(tracks.upcoming_length_ms())} total")
    if tracks.loop is not LoopMode.OFF:
        footer.append(f"loop: {LOOP_LABELS[tracks.loop]}")
    embed = discord.Embed(title="Queue", description="\n".join(lines), color=EMBED_COLOR)
    embed.set_footer(text=" · ".join(footer))
    return embed


def added_message(
    result: resolver.LoadResult, added: int, player: MusicPlayer, started: bool
) -> str:
    if result.collection is None:
        entry = result.entries[0]
        if started:
            return f"🎶 Starting {entry_link(entry)} `{entry_duration(entry)}`"
        position = len(player.tracks.upcoming)
        return f"➕ Queued {entry_link(entry)} `{entry_duration(entry)}` at position {position}."

    name = discord.utils.escape_markdown(result.collection)
    text = f"➕ Queued **{songs(added)}** from **{name}**."
    if added < len(result.entries):
        text += f" The queue is full, so {len(result.entries) - added} didn't fit."
    if result.note:
        text += f"\n-# {result.note}"
    return text


class MusicCog(commands.Cog):
    def __init__(self, bot: VoldemarBot) -> None:
        self.bot = bot

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, GuardError):
            message = str(original)
        else:
            name = interaction.command.name if interaction.command else "?"
            log.error("/%s failed", name, exc_info=original)
            message = "Something went wrong. The details are in logs/voldemar.log."
        with contextlib.suppress(discord.HTTPException):
            await reply_error(interaction, message)

    # --- Playback ------------------------------------------------------------------------------

    @app_commands.command(description="Play a song, playlist or album from a link, or search")
    @app_commands.describe(
        query="A YouTube, YouTube Music, Spotify, Apple Music or SoundCloud link, or a song name"
    )
    @app_commands.guild_only()
    async def play(
        self, interaction: discord.Interaction, query: app_commands.Range[str, 1, 500]
    ) -> None:
        channel = check_can_join(interaction)
        await interaction.response.defer(thinking=True)
        assert self.bot.http_session is not None
        try:
            # Load first: a bad link shouldn't make the bot join the channel for nothing.
            result = await resolver.load(query, interaction.user.id, self.bot.http_session)
            player = await join(interaction, channel)
            added = player.tracks.add(result.entries)
        except (resolver.LoadError, GuardError) as e:
            await reply_error(interaction, str(e))
            return
        except QueueFull:
            limit = self.bot.settings.max_queue_size
            await reply_error(interaction, f"The queue is full ({limit} songs).")
            return
        started = await player.start_if_idle()
        if not started:
            player.queue_changed()
        await reply(interaction, added_message(result, added, player, started))

    @app_commands.command(description="Pause the music")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        player = require_player(interaction, playing=True)
        if player.paused:
            raise GuardError("Already paused. Use /resume to continue.")
        await player.pause(True)
        await reply(interaction, f"⏸️ Paused by {interaction.user.mention}.")

    @app_commands.command(description="Continue playing after /pause")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        player = require_player(interaction, playing=True)
        if not player.paused:
            raise GuardError("The music isn't paused.")
        await player.pause(False)
        await reply(interaction, f"▶️ Resumed by {interaction.user.mention}.")

    @app_commands.command(description="Skip the current song, or jump to a position in the queue")
    @app_commands.describe(to="Jump straight to this queue position (see /queue)")
    @app_commands.guild_only()
    async def skip(
        self, interaction: discord.Interaction, to: app_commands.Range[int, 1] | None = None
    ) -> None:
        player = require_player(interaction, playing=True)
        skipped = player.tracks.current
        assert skipped is not None
        if to is not None and to > (count := len(player.tracks.upcoming)):
            raise GuardError(f"There's no position {to}: the queue has {songs(count)}.")
        await interaction.response.defer()  # looking up the next Spotify song can take a moment
        entry = await player.skip_to(to) if to is not None else await player.skip_current()
        text = f"⏭️ {interaction.user.mention} skipped {entry_link(skipped)}."
        if entry is None:
            text += " That was the last song in the queue."
        await reply(interaction, text)

    @app_commands.command(description="Play the previous song again")
    @app_commands.guild_only()
    async def previous(self, interaction: discord.Interaction) -> None:
        player = require_player(interaction)
        if not player.tracks.history:
            raise GuardError("There's no previous song.")
        await interaction.response.defer()
        entry = await player.play_previous()
        if entry is None:
            await reply(interaction, "⚠️ Couldn't go back to the previous song.")
            return
        await reply(interaction, f"⏮️ {interaction.user.mention} went back to {entry_link(entry)}.")

    @app_commands.command(description="Stop the music, clear the queue and leave the channel")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        player = require_player(interaction)
        await player.teardown()
        await reply(interaction, f"⏹️ {interaction.user.mention} stopped the music. See you! 👋")

    @app_commands.command(description="Jump to a point in the current song")
    @app_commands.describe(position="Where to jump to, e.g. 1:23, 83 or 1m23s")
    @app_commands.guild_only()
    async def seek(
        self, interaction: discord.Interaction, position: app_commands.Range[str, 1, 16]
    ) -> None:
        player = require_player(interaction, playing=True)
        track = player.current
        if track is None or track.is_stream or not track.is_seekable:
            raise GuardError("You can't seek in this song.")
        try:
            target = parse_time(position)
        except ValueError:
            raise GuardError("Use a time like 1:23, 83 or 1m23s.") from None
        if target >= track.length:
            raise GuardError(f"This song is only {format_duration(track.length)} long.")
        await player.seek(target)
        await reply(interaction, f"⏩ Jumped to `{format_duration(target)}`.")

    @app_commands.command(description="Show or change the volume")
    @app_commands.describe(level="New volume from 0 to 150 (100 is normal)")
    @app_commands.guild_only()
    async def volume(
        self,
        interaction: discord.Interaction,
        level: app_commands.Range[int, 0, 150] | None = None,
    ) -> None:
        player = require_player(interaction)
        if level is None:
            await reply(interaction, f"🔊 The volume is {player.volume}%.", ephemeral=True)
            return
        await player.set_volume(level)
        await reply(interaction, f"🔊 {interaction.user.mention} set the volume to {level}%.")

    # --- Queue ---------------------------------------------------------------------------------

    @app_commands.command(description="Show the queue")
    @app_commands.describe(page="Page number")
    @app_commands.guild_only()
    async def queue(
        self, interaction: discord.Interaction, page: app_commands.Range[int, 1] = 1
    ) -> None:
        player = get_player(interaction.guild)
        if player is None or (player.tracks.current is None and not player.tracks.upcoming):
            raise GuardError("The queue is empty. Add something with /play.")
        await reply(interaction, embed=queue_embed(player, page))

    @app_commands.command(description="Show the song that's playing")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        player = get_player(interaction.guild)
        if player is None or player.tracks.current is None:
            raise GuardError("Nothing is playing right now.")
        embed = now_playing_embed(player, player.tracks.current, show_progress=True)
        await reply(interaction, embed=embed)

    @app_commands.command(description="Repeat the current song or the whole queue")
    @app_commands.describe(mode="What to repeat")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Off", value=LoopMode.OFF.value),
            app_commands.Choice(name="Current song", value=LoopMode.TRACK.value),
            app_commands.Choice(name="Whole queue", value=LoopMode.QUEUE.value),
        ]
    )
    @app_commands.guild_only()
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        player = require_player(interaction)
        player.tracks.loop = LoopMode(mode.value)
        player.queue_changed()
        label = LOOP_LABELS[player.tracks.loop]
        await reply(interaction, f"🔁 {interaction.user.mention} set loop to **{label}**.")

    @app_commands.command(description="Shuffle the upcoming songs")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player = require_player(interaction)
        count = len(player.tracks.upcoming)
        if count < 2:
            raise GuardError("There need to be at least two songs in the queue to shuffle.")
        player.tracks.shuffle()
        player.queue_changed()
        await reply(interaction, f"🔀 {interaction.user.mention} shuffled {songs(count)}.")

    @app_commands.command(description="Remove a song from the queue")
    @app_commands.describe(position="The song's position in /queue")
    @app_commands.guild_only()
    async def remove(
        self, interaction: discord.Interaction, position: app_commands.Range[int, 1]
    ) -> None:
        player = require_player(interaction)
        try:
            entry = player.tracks.remove(position)
        except IndexError:
            count = songs(len(player.tracks.upcoming))
            raise GuardError(f"There's no position {position}: the queue has {count}.") from None
        player.queue_changed()
        await reply(interaction, f"🗑️ {interaction.user.mention} removed {entry_link(entry)}.")

    @app_commands.command(description="Move a song to another position in the queue")
    @app_commands.describe(from_="The song's current position", to="Its new position")
    @app_commands.rename(from_="from")
    @app_commands.guild_only()
    async def move(
        self,
        interaction: discord.Interaction,
        from_: app_commands.Range[int, 1],
        to: app_commands.Range[int, 1],
    ) -> None:
        player = require_player(interaction)
        try:
            entry = player.tracks.move(from_, to)
        except IndexError:
            raise GuardError(f"Positions go from 1 to {len(player.tracks.upcoming)}.") from None
        player.queue_changed()
        await reply(interaction, f"↕️ Moved {entry_link(entry)} to position {to}.")

    @app_commands.command(description="Remove all upcoming songs (the current one keeps playing)")
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction) -> None:
        player = require_player(interaction)
        count = player.tracks.clear()
        if count == 0:
            raise GuardError("The queue is already empty.")
        await reply(interaction, f"🧹 {interaction.user.mention} cleared {songs(count)}.")

    @app_commands.command(name="help", description="Show what Voldemar can do")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Voldemar — music commands", description=HELP_TEXT, color=EMBED_COLOR
        )
        await reply(interaction, embed=embed, ephemeral=True)
