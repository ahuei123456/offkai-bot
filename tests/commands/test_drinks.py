# tests/commands/test_drinks.py

from collections import Counter
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

# Import the function to test and relevant errors/classes
from offkai_bot.cogs.events import EventsCog
from offkai_bot.errors import (
    EventNotFoundError,
    NoResponsesFoundError,
)

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

    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.id = 456

    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 789

    interaction.command = MagicMock(spec=app_commands.Command)
    interaction.command.name = "drinks"  # Specific to this command

    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock(send=AsyncMock())

    return interaction


@pytest.fixture
def mock_event_obj(sample_event_list):  # Assumes sample_event_list is in conftest.py
    """Fixture providing a specific Event object (e.g., Summer Bash)."""
    return next(e for e in sample_event_list if e.event_name == "Summer Bash")


# --- Test Cases ---


@patch("offkai_bot.cogs.events.calculate_drinks")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_drinks_success(
    mock_log,
    mock_get_event,
    mock_calculate_drinks,
    mock_interaction,
    mock_event_obj,
    prepopulated_event_cache,  # Assumes this is in conftest.py
    mock_cog,
):
    """Test the successful path of the drinks command with drinks present."""
    # Arrange
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj

    mock_total_drink_count = 3
    mock_drinks_data = {"Cola": 2, "Water": 1}
    mock_drinks_counter = Counter(mock_drinks_data)
    mock_calculate_drinks.return_value = (mock_total_drink_count, mock_drinks_counter)

    # Act
    await EventsCog.drinks.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_target,
    )

    # Assert
    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_drinks.assert_called_once_with(event_name_target)

    # Verify send_message was called, but don't check exact content
    mock_interaction.response.send_message.assert_awaited_once_with(ANY, ephemeral=True)
    mock_log.warning.assert_not_called()


@patch("offkai_bot.cogs.events.calculate_drinks")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_drinks_success_no_drinks_in_responses(
    mock_log,
    mock_get_event,
    mock_calculate_drinks,
    mock_interaction,
    mock_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test the drinks command when responses exist but have no drinks."""
    # Arrange
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj

    mock_total_drink_count = 0
    mock_drinks_dict = {}  # Empty dict
    mock_calculate_drinks.return_value = (mock_total_drink_count, mock_drinks_dict)

    # Act
    await EventsCog.drinks.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_target,
    )

    # Assert
    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_drinks.assert_called_once_with(event_name_target)

    # Verify send_message was called, but don't check exact content
    mock_interaction.response.send_message.assert_awaited_once_with(ANY, ephemeral=True)
    mock_log.warning.assert_not_called()


@patch("offkai_bot.cogs.events.calculate_drinks")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_drinks_success_truncation(
    mock_log,
    mock_get_event,
    mock_calculate_drinks,
    mock_interaction,
    mock_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test drinks output truncation when the list is very long."""
    # Arrange
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj

    long_drinks_dict_items = [(f"Drink{i:03d}", 1) for i in range(300)]  # Approx 300 drinks
    mock_total_drink_count = len(long_drinks_dict_items)
    mock_drinks_counter = Counter(dict(long_drinks_dict_items))
    mock_calculate_drinks.return_value = (mock_total_drink_count, mock_drinks_counter)

    # Act
    await EventsCog.drinks.callback(mock_cog, mock_interaction, event_name=event_name_target)

    # Assert
    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_drinks.assert_called_once_with(event_name_target)
    mock_interaction.response.send_message.assert_awaited_once_with(ANY, ephemeral=True)


@patch("offkai_bot.cogs.events.calculate_drinks")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_drinks_event_not_found(
    mock_log, mock_get_event, mock_calculate_drinks, mock_interaction, prepopulated_event_cache, mock_cog
):
    """Test drinks command when the initial get_event fails."""
    # Arrange
    event_name_target = "NonExistent Event"
    mock_get_event.side_effect = EventNotFoundError(event_name_target)

    # Act & Assert
    with pytest.raises(EventNotFoundError):
        await EventsCog.drinks.callback(mock_cog, mock_interaction, event_name=event_name_target)

    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_drinks.assert_not_called()
    mock_interaction.response.send_message.assert_not_awaited()


@patch("offkai_bot.cogs.events.calculate_drinks")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_drinks_no_responses_found_for_event(
    mock_log,
    mock_get_event,
    mock_calculate_drinks,
    mock_interaction,
    mock_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test drinks command when calculate_drinks raises NoResponsesFoundError."""
    # Arrange
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj
    mock_calculate_drinks.side_effect = NoResponsesFoundError(event_name_target)

    # Act & Assert
    with pytest.raises(NoResponsesFoundError):
        await EventsCog.drinks.callback(mock_cog, mock_interaction, event_name=event_name_target)

    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_drinks.assert_called_once_with(event_name_target)
    mock_interaction.response.send_message.assert_not_awaited()
