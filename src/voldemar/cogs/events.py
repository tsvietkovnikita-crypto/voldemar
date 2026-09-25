"""Lavalink events forwarded to the players, plus leaving empty voice channels."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
import wavelink
from discord.ext import commands

from voldemar.music.guards import get_player
from voldemar.music.player import MusicPlayer

if TYPE_CHECKING:
    from voldemar.bot import VoldemarBot

log = logging.getLogger(__name__)


class EventsCog(commands.Cog):
    def __init__(self, bot: VoldemarBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload) -> None:
        log.info("Connected to Lavalink at %s (resumed: %s)", payload.node.uri, payload.resumed)

    @commands.Cog.listener()
    async def on_wavelink_node_disconnected(
        self, payload: wavelink.NodeDisconnectedEventPayload
    ) -> None:
        log.warning("Lost the connection to Lavalink; reconnecting in the background")
        for voice_client in list(self.bot.voice_clients):
            if isinstance(voice_client, MusicPlayer):
                await voice_client.notify(
                    "⚠️ Lost the connection to the music server, so the music stopped. "
                    "Try /play again in a moment."
                )
                await voice_client.teardown()

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload) -> None:
        if isinstance(payload.player, MusicPlayer):
            await payload.player.on_track_start()

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload) -> None:
        if isinstance(payload.player, MusicPlayer):
            await payload.player.on_track_end(payload.track, payload.reason)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(
        self, payload: wavelink.TrackExceptionEventPayload
    ) -> None:
        if isinstance(payload.player, MusicPlayer):
            payload.player.last_error = payload.exception.get("message") or "unknown error"

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(self, payload: wavelink.TrackStuckEventPayload) -> None:
        if isinstance(payload.player, MusicPlayer):
            log.warning("Track %r got stuck; skipping it", payload.track.title)
            await payload.player.skip_current()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        player = get_player(member.guild)
        if player is None or player.channel is None:
            return
        # Someone joined or left the bot's channel, or the bot itself was moved.
        is_bot = self.bot.user is not None and member.id == self.bot.user.id
        if is_bot or player.channel in (before.channel, after.channel):
            player.check_listeners()
