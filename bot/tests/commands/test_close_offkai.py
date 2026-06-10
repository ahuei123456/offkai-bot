# tests/commands/test_close_offkai.py

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

# Import the main module to access the command and client
from offkai_bot.cogs.events import EventsCog

# Import specific errors that perform_close_event might raise
from offkai_bot.errors import EventNotFoundError

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

    interaction.command = MagicMock(spec=app_commands.Command)
    interaction.command.name = "close_offkai"

    # Mock response methods
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    # Simple mock client if needed, but not used for patching global state
    interaction.client = MagicMock(spec=discord.Client)

    return interaction


# --- Test Cases ---


# Patch the function that the command now calls
@patch("offkai_bot.cogs.events.perform_close_event", new_callable=AsyncMock)
async def test_close_offkai_command_success_with_message(mock_perform_close, mock_interaction, mock_cog):
    """Test the close_offkai command successfully calls perform_close_event and responds."""
    # Arrange
    event_name_to_close = "Summer Bash"
    close_text = "Responses are now closed!"
    # No need to mock return value unless subsequent code uses it

    # Act
    await EventsCog.close_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    # 1. Check that perform_close_event was called correctly with mock_cog.bot
    mock_perform_close.assert_awaited_once_with(
        mock_cog.bot,  # Check bot instance from cog is passed
        event_name_to_close,
        close_text,
    )

    # 2. Check that the interaction response was sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_close}' have been closed."
    )


@patch("offkai_bot.cogs.events.perform_close_event", new_callable=AsyncMock)
async def test_close_offkai_command_success_no_message(mock_perform_close, mock_interaction, mock_cog):
    """Test the close_offkai command successfully calls perform_close_event without a close message."""
    # Arrange
    event_name_to_close = "Summer Bash"
    # No need to mock return value

    # Act
    await EventsCog.close_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_close,
        close_msg=None,  # Explicitly None
    )

    # Assert
    # 1. Check that perform_close_event was called correctly
    mock_perform_close.assert_awaited_once_with(
        mock_cog.bot,
        event_name_to_close,
        None,  # Check None is passed
    )

    # 2. Check that the interaction response was sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_close}' have been closed."
    )


@patch("offkai_bot.cogs.events.perform_close_event", new_callable=AsyncMock)
async def test_close_offkai_command_error_propagation(mock_perform_close, mock_interaction, mock_cog):
    """Test that errors from perform_close_event are propagated by the command."""
    # Arrange
    event_name_to_close = "NonExistent Event"
    error_to_raise = EventNotFoundError(event_name_to_close)
    mock_perform_close.side_effect = error_to_raise

    # Act & Assert
    # Check that the specific error raised by the mock is re-raised by the callback
    with pytest.raises(EventNotFoundError) as excinfo:
        await EventsCog.close_offkai.callback(
            mock_cog,
            mock_interaction,
            event_name=event_name_to_close,
            close_msg="Attempting to close",
        )

    # Ensure the raised exception is the one we simulated
    assert excinfo.value is error_to_raise

    # Assert that perform_close_event was called
    mock_perform_close.assert_awaited_once_with(
        mock_cog.bot,
        event_name_to_close,
        "Attempting to close",
    )

    # Assert that the success response was NOT sent
    mock_interaction.response.send_message.assert_not_awaited()
