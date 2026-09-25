"""The Discord client: intents, cogs and slash-command registration."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from voldemar.cogs.music import MusicCog
from voldemar.config import Settings

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

    async def setup_hook(self) -> None:
        await self.add_cog(MusicCog(self))
        await self.sync_commands()

    async def sync_commands(self) -> None:
        if not self.settings.guild_ids:
            synced = await self.tree.sync()
            log.info("Registered %d global slash commands (may take a minute to show)", len(synced))
            return

        for guild_id in self.settings.guild_ids:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            try:
                synced = await self.tree.sync(guild=guild)
            except discord.Forbidden:
                log.error(
                    "Can't register commands in server %s: invite the bot there first", guild_id
                )
                continue
            log.info("Registered %d slash commands in server %s", len(synced), guild_id)

        # Drop global copies so the servers above don't show every command twice.
        self.tree.clear_commands(guild=None)
        await self.tree.sync()

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info(
            "Logged in as %s (id %s) in %d server(s)", self.user, self.user.id, len(self.guilds)
        )
        log.info("Invite link: %s", invite_url(self.user.id))
