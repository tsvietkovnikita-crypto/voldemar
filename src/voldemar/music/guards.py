"""Checks shared by slash commands and buttons: voice channels, permissions and connecting."""

from __future__ import annotations

import contextlib

import discord
import wavelink

from voldemar.music.player import MusicPlayer

VoiceChannel = discord.VoiceChannel | discord.StageChannel


class GuardError(Exception):
    """The action can't run right now. The message is shown only to the user who tried it."""


def get_player(guild: discord.Guild | None) -> MusicPlayer | None:
    voice_client = guild.voice_client if guild is not None else None
    return voice_client if isinstance(voice_client, MusicPlayer) else None


def user_channel(interaction: discord.Interaction) -> VoiceChannel | None:
    member = interaction.user
    if isinstance(member, discord.Member) and member.voice is not None:
        return member.voice.channel
    return None


def require_player(interaction: discord.Interaction, *, playing: bool = False) -> MusicPlayer:
    """This server's player, used from the bot's own voice channel."""
    player = get_player(interaction.guild)
    if player is None or player.channel is None:
        raise GuardError("I'm not in a voice channel. Use /play to start the music.")
    if user_channel(interaction) != player.channel:
        raise GuardError(f"Join {player.channel.mention} to control the music.")
    if playing and player.tracks.current is None:
        raise GuardError("Nothing is playing right now.")
    return player


def check_can_join(interaction: discord.Interaction) -> VoiceChannel:
    """The user's voice channel, if the bot may join it (or is already there). Doesn't connect."""
    channel = user_channel(interaction)
    if channel is None:
        raise GuardError("Join a voice channel first, then use /play.")
    if isinstance(channel, discord.StageChannel):
        raise GuardError("Stage channels aren't supported. Use a normal voice channel.")

    assert interaction.guild is not None
    permissions = channel.permissions_for(interaction.guild.me)
    if not (permissions.view_channel and permissions.connect and permissions.speak):
        raise GuardError(f"I need the **Connect** and **Speak** permissions in {channel.mention}.")

    player = get_player(interaction.guild)
    if player is None or player.channel is None:
        full = channel.user_limit and len(channel.members) >= channel.user_limit
        if full and not permissions.move_members:
            raise GuardError(f"{channel.mention} is full.")
    elif player.channel != channel and not player.can_move:
        raise GuardError(
            f"I'm already playing in {player.channel.mention}. Join that channel to add songs."
        )
    return channel


async def join(interaction: discord.Interaction, channel: VoiceChannel) -> MusicPlayer:
    """Connect to `channel` (or move there) and return the player."""
    assert interaction.guild is not None
    player = get_player(interaction.guild)
    try:
        if player is None:
            player = await channel.connect(cls=MusicPlayer, self_deaf=True, timeout=15)
            player.text_channel = interaction.channel  # type: ignore[assignment]
            await player.set_volume(player.bot.settings.default_volume)
        elif player.channel != channel:
            await player.move_to(channel)
    except wavelink.InvalidNodeException:
        raise GuardError(
            "The music server isn't connected yet. Try again in a few seconds."
        ) from None
    except (wavelink.ChannelTimeoutException, TimeoutError):
        if (stale := get_player(interaction.guild)) is not None:
            with contextlib.suppress(Exception):
                await stale.disconnect()
        raise GuardError("Couldn't connect to the voice channel in time. Try again.") from None
    return player
