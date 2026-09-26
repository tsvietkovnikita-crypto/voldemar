"""The "Now playing" embed and the buttons under it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from voldemar.music.queue import LoopMode, QueueEntry
from voldemar.ui.formatting import entry_duration, entry_link, progress_bar, source_name

if TYPE_CHECKING:
    from voldemar.music.player import MusicPlayer

EMBED_COLOR = 0x1DB954
NO_MENTIONS = discord.AllowedMentions.none()
LOOP_BUTTON_LABELS = {
    LoopMode.OFF: "Loop: off",
    LoopMode.TRACK: "Loop: song",
    LoopMode.QUEUE: "Loop: queue",
}


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


class NowPlayingView(discord.ui.View):
    """Pause/resume, skip, stop, loop and shuffle buttons.

    One instance is registered at startup (`bot.add_view`) and handles every click through the
    fixed custom IDs, so buttons keep answering after a restart. Panels are drawn with `render`,
    which returns a stopped copy: discord.py doesn't keep stopped views in memory per message.
    """

    def __init__(self, *, paused: bool = False, loop: LoopMode = LoopMode.OFF) -> None:
        super().__init__(timeout=None)
        self.toggle_button.label = "Resume" if paused else "Pause"
        self.toggle_button.emoji = "▶️" if paused else "⏸️"
        self.loop_button.label = LOOP_BUTTON_LABELS[loop]
        if loop is not LoopMode.OFF:
            self.loop_button.style = discord.ButtonStyle.success

    @classmethod
    def render(cls, player: MusicPlayer) -> NowPlayingView:
        view = cls(paused=player.paused, loop=player.tracks.loop)
        view.stop()
        return view

    @discord.ui.button(emoji="⏸️", label="Pause", custom_id="voldemar:np:toggle")
    async def toggle_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if (player := await _player_for(interaction, playing=True)) is None:
            return
        await player.pause(not player.paused)
        await _redraw(interaction, player)

    @discord.ui.button(emoji="⏭️", label="Skip", custom_id="voldemar:np:skip")
    async def skip_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if (player := await _player_for(interaction, playing=True)) is None:
            return
        skipped = player.tracks.current
        assert skipped is not None
        await interaction.response.defer()  # the next song's panel replaces this one
        entry = await player.skip_current()
        text = f"⏭️ {interaction.user.mention} skipped {entry_link(skipped)}."
        if entry is None:
            text += " That was the last song in the queue."
        await interaction.followup.send(text, allowed_mentions=NO_MENTIONS, suppress_embeds=True)

    @discord.ui.button(
        emoji="⏹️", label="Stop", style=discord.ButtonStyle.danger, custom_id="voldemar:np:stop"
    )
    async def stop_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if (player := await _player_for(interaction)) is None:
            return
        await player.teardown()  # also removes the buttons from this panel
        await interaction.response.send_message(
            f"⏹️ {interaction.user.mention} stopped the music. See you! 👋",
            allowed_mentions=NO_MENTIONS,
        )

    @discord.ui.button(emoji="🔁", label="Loop: off", custom_id="voldemar:np:loop")
    async def loop_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if (player := await _player_for(interaction, playing=True)) is None:
            return
        player.tracks.loop = player.tracks.loop.next()
        player.state_changed(redraw=False)
        await _redraw(interaction, player)

    @discord.ui.button(emoji="🔀", label="Shuffle", custom_id="voldemar:np:shuffle")
    async def shuffle_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if (player := await _player_for(interaction, playing=True)) is None:
            return
        count = len(player.tracks.upcoming)
        if count < 2:
            await interaction.response.send_message(
                "❌ There need to be at least two songs in the queue to shuffle.", ephemeral=True
            )
            return
        player.tracks.shuffle()
        player.state_changed(redraw=False)
        await _redraw(interaction, player)
        await interaction.followup.send(
            f"🔀 {interaction.user.mention} shuffled {count} songs.", allowed_mentions=NO_MENTIONS
        )


async def _player_for(
    interaction: discord.Interaction, *, playing: bool = False
) -> MusicPlayer | None:
    """The player, if this user may control it; otherwise tell them why not and return None."""
    # Imported here because guards -> player -> now_playing would otherwise be a circular import.
    from voldemar.music.guards import GuardError, require_player

    try:
        return require_player(interaction, playing=playing)
    except GuardError as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        return None


async def _redraw(interaction: discord.Interaction, player: MusicPlayer) -> None:
    """Update the clicked panel to the player's new state."""
    current = player.tracks.current
    if current is None:
        await interaction.response.edit_message(view=None)
        return
    await interaction.response.edit_message(
        embed=now_playing_embed(player, current), view=NowPlayingView.render(player)
    )
