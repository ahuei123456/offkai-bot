# tests/test_allowed_mentions.py
"""Tests for the client-wide mention suppression default (issue #102).

Organizer-supplied text (broadcast/update/close/announce messages) is relayed
verbatim by the bot, so the client must default to AllowedMentions.none() and
individual sends must explicitly opt in where a ping is intended.
"""

from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands
from offkai_bot.cogs.general import GeneralCog
from offkai_bot.main import OffkaiClient


def test_client_suppresses_all_mentions_by_default():
    """The client must be constructed with AllowedMentions.none() so relayed
    organizer text can never ping @everyone/@here/roles/users."""
    client = OffkaiClient(intents=discord.Intents.default())

    assert client.allowed_mentions is not None
    assert client.allowed_mentions.to_dict() == discord.AllowedMentions.none().to_dict()


async def test_hello_opts_into_user_mentions():
    """/hello greets the invoking user by mention and must opt in to user pings."""
    cog = GeneralCog(MagicMock(spec=commands.Bot))
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.mention = "<@42>"
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cog.hello.callback(cog, interaction)

    interaction.response.send_message.assert_awaited_once()
    kwargs = interaction.response.send_message.await_args.kwargs
    assert kwargs["allowed_mentions"].users is True
