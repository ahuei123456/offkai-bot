# tests/commands/test_context_validation.py

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord import app_commands
from discord.ext import commands
from offkai_bot.cogs.events import EventsCog
from offkai_bot.errors import EventNotFoundError, InvalidChannelTypeError

# pytest marker for async tests
pytestmark = pytest.mark.asyncio

# --- Fixtures ---


@pytest.fixture
def mock_cog():
    """Fixture to create a mock EventsCog instance."""
    bot = MagicMock(spec=commands.Bot)
    return EventsCog(bot)


@pytest.fixture
def mock_interaction():
    """Fixture to create a mock discord.Interaction with necessary attributes."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 123
    interaction.user.__str__.return_value = "TestUser#1234"

    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 789

    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.id = 456

    interaction.command = MagicMock(spec=app_commands.Command)
    interaction.command.name = "mock_command"

    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock(send=AsyncMock())

    return interaction


# Each command with the extra kwargs (beyond event_name) needed to invoke it.
# These commands operate on stored event data (or only produce reports), so they
# accept both guild text channels and guild threads.
COMMANDS_REQUIRING_CONTEXT = [
    ("close_offkai", {}),
    ("reopen_offkai", {}),
    ("archive_offkai", {}),
    ("broadcast", {"message": "Hello"}),
    ("delete_response", {"member": MagicMock(spec=discord.Member)}),
    ("promote", {"username": "123"}),
    ("attendance", {}),
    ("attendance_report", {}),
    ("waitlist", {}),
    ("drinks", {}),
]


# --- Test Cases ---


@pytest.mark.parametrize("command_name, extra_kwargs", COMMANDS_REQUIRING_CONTEXT)
async def test_command_rejects_non_text_channel(mock_cog, mock_interaction, command_name, extra_kwargs):
    """Commands should raise InvalidChannelTypeError before doing any work when not in a guild text channel."""
    # Arrange
    mock_interaction.channel = MagicMock(spec=discord.DMChannel)
    command = getattr(EventsCog, command_name)

    # Act / Assert
    with pytest.raises(InvalidChannelTypeError):
        await command.callback(mock_cog, mock_interaction, event_name="Summer Bash", **extra_kwargs)

    # The interaction must not have been acknowledged before validation failed
    mock_interaction.response.defer.assert_not_called()
    mock_interaction.response.send_message.assert_not_called()


@pytest.mark.parametrize("command_name, extra_kwargs", COMMANDS_REQUIRING_CONTEXT)
async def test_command_rejects_missing_guild(mock_cog, mock_interaction, command_name, extra_kwargs):
    """Commands should raise InvalidChannelTypeError when invoked outside a guild."""
    # Arrange
    mock_interaction.guild = None
    command = getattr(EventsCog, command_name)

    # Act / Assert
    with pytest.raises(InvalidChannelTypeError):
        await command.callback(mock_cog, mock_interaction, event_name="Summer Bash", **extra_kwargs)

    mock_interaction.response.defer.assert_not_called()
    mock_interaction.response.send_message.assert_not_called()


@pytest.mark.parametrize("command_name, extra_kwargs", COMMANDS_REQUIRING_CONTEXT)
async def test_command_allows_guild_thread(mock_cog, mock_interaction, command_name, extra_kwargs):
    """Event-management/report commands should pass context validation when run from a guild thread.

    The event cache is empty, so getting past the channel check surfaces as
    EventNotFoundError — raising InvalidChannelTypeError instead would mean the
    thread context was wrongly rejected.
    """
    # Arrange
    mock_interaction.channel = MagicMock(spec=discord.Thread)
    command = getattr(EventsCog, command_name)

    # Act / Assert
    with pytest.raises(EventNotFoundError):
        await command.callback(mock_cog, mock_interaction, event_name="Summer Bash", **extra_kwargs)


async def test_modify_offkai_rejects_guild_thread(mock_cog, mock_interaction):
    """Commands that need the current channel as the event's parent stay strict: threads are rejected."""
    # Arrange
    mock_interaction.channel = MagicMock(spec=discord.Thread)

    # Act / Assert
    with pytest.raises(InvalidChannelTypeError):
        await EventsCog.modify_offkai.callback(
            mock_cog, mock_interaction, event_name="Summer Bash", update_msg="Update!"
        )

    mock_interaction.response.defer.assert_not_called()
    mock_interaction.response.send_message.assert_not_called()


async def test_create_offkai_rejects_guild_thread(mock_cog, mock_interaction):
    """create_offkai creates the event thread from the current channel, so a thread context is rejected."""
    # Arrange
    mock_interaction.channel = MagicMock(spec=discord.Thread)

    # Act / Assert
    with pytest.raises(InvalidChannelTypeError):
        await EventsCog.create_offkai.callback(
            mock_cog,
            mock_interaction,
            event_name="Summer Bash",
            venue="Venue",
            address="Address",
            google_maps_link="https://maps.example.com",
            date_time="3024-08-15 19:30",
        )

    mock_interaction.response.defer.assert_not_called()
    mock_interaction.response.send_message.assert_not_called()
