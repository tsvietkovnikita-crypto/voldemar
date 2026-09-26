"""The Discord client: intents, cogs, the Lavalink connection and slash-command registration."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
import discord
import wavelink
from discord.ext import commands

from voldemar.cogs.events import EventsCog
from voldemar.cogs.music import MusicCog
from voldemar.config import Settings
from voldemar.ui.now_playing import NowPlayingView

log = logging.getLogger(__name__)

# View Channel, Send Messages, Embed Links, Connect, Speak (= 3165184)
INVITE_PERMISSIONS = discord.Permissions(
    view_channel=True, send_messages=True, embed_links=True, connect=True, speak=True
)


def invite_url(client_id: int) -> str:
    return discord.utils.oauth_url(
        client_id, permissions=INVITE_PERMISSIONS, scopes=("bot", "applications.commands")
    )


class VoldemarBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        # Audio goes through Lavalink; discord.py's own voice stack (PyNaCl, davey) is never used.
        discord.VoiceClient.warn_nacl = False
        discord.VoiceClient.warn_dave = False

        # Slash commands and voice only: no privileged intents (message content, members) needed.
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.settings = settings
        self.http_session: aiohttp.ClientSession | None = None
        self._lavalink_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        self.http_session = aiohttp.ClientSession()
        # Connecting retries until Lavalink answers; don't hold up the Discord login meanwhile.
        self._lavalink_task = asyncio.create_task(self._connect_lavalink())
        await self.add_cog(MusicCog(self))
        await self.add_cog(EventsCog(self))
        self.add_view(NowPlayingView())  # answers now-playing buttons, even on older messages
        await self.sync_commands()

    async def _connect_lavalink(self) -> None:
        node = wavelink.Node(
            uri=self.settings.lavalink_uri,
            password=self.settings.lavalink_password,
            # Leaving idle or empty channels is handled by MusicPlayer itself.
            inactive_player_timeout=None,
            inactive_channel_tokens=None,
        )
        nodes = await wavelink.Pool.connect(nodes=[node], client=self)
        if not nodes:
            log.error(
                "Couldn't connect to Lavalink at %s. If the log above mentions authentication, "
                "LAVALINK_PASSWORD doesn't match the running Lavalink.",
                self.settings.lavalink_uri,
            )

    async def close(self) -> None:
        await super().close()  # also leaves all voice channels
        if self._lavalink_task is not None:
            self._lavalink_task.cancel()
        await wavelink.Pool.close()
        if self.http_session is not None:
            await self.http_session.close()

    async def sync_commands(self) -> None:
        if not self.settings.guild_ids:
            synced = await self.tree.sync()
            log.info("Registered %d global slash commands (may take a minute to show)", len(synced))
            return

        for guild_id in self.settings.guild_ids:
            await self._sync_guild(discord.Object(id=guild_id))

        # Unregister global copies so those servers don't list every command twice. The commands
        # stay in the local tree, so servers that invite the bot later still get a copy.
        commands_ = self.tree.get_commands()
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        for command in commands_:
            self.tree.add_command(command)

    async def _sync_guild(self, guild: discord.abc.Snowflake) -> None:
        self.tree.copy_global_to(guild=guild)
        try:
            synced = await self.tree.sync(guild=guild)
        except discord.Forbidden:
            log.warning(
                "Can't register commands in server %s yet: invite the bot with the link below",
                guild.id,
            )
            return
        log.info("Registered %d slash commands in server %s", len(synced), guild.id)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        log.info("Joined server %s (%s)", guild.name, guild.id)
        if guild.id in self.settings.guild_ids:
            await self._sync_guild(guild)

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info(
            "Logged in as %s (id %s) in %d server(s)", self.user, self.user.id, len(self.guilds)
        )
        log.info("Invite link: %s", invite_url(self.user.id))
