"""Slash commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from voldemar.bot import VoldemarBot

HELP_TEXT = """\
**Playback**
`/play query` — a link or search text; joins your voice channel
`/pause` · `/resume` · `/stop` (clears the queue and leaves)
`/skip [to]` — skip, or jump to a queue position · `/previous`
`/seek position` — e.g. `1:23` · `/volume level` — 0 to 150

**Queue**
`/queue [page]` · `/nowplaying`
`/loop mode` — off, track or queue · `/shuffle` · `/clear`
`/remove position` · `/move from to`

**Supported links**
YouTube and YouTube Music (videos, playlists), Spotify and Apple Music (songs, albums, \
playlists, artists), SoundCloud, Bandcamp, Twitch and direct audio links. \
Anything else is searched on YouTube Music.
"""


class MusicCog(commands.Cog):
    def __init__(self, bot: VoldemarBot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Show what Voldemar can do")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Voldemar — music commands", description=HELP_TEXT, color=0x5865F2
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
