# tests/commands/test_attendance.py

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands

# Import the function to test and relevant errors/classes
from offkai_bot import main
from offkai_bot.errors import (
    EventNotFoundError,
    NoResponsesFoundError,
)

# pytest marker for async tests
pytestmark = pytest.mark.asyncio

# --- Fixtures ---


@pytest.fixture
def mock_interaction():
    """Fixture to create a mock discord.Interaction with necessary attributes."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 123
    interaction.user.__str__.return_value = "TestUser#1234"

    # Mock channel as a TextChannel initially
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.id = 456
    interaction.channel.create_thread = AsyncMock()  # Mock the async method

    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 789

    interaction.command = MagicMock(spec=app_commands.Command)
    interaction.command.name = "attendance"

    # Mock response methods
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock(send=AsyncMock())  # In case response is done

    return interaction


@pytest.fixture
def mock_event_obj(sample_event_list):
    """Fixture providing a specific Event object (e.g., Summer Bash)."""
    return next(e for e in sample_event_list if e.event_name == "Summer Bash")


# --- Test Cases ---


@patch("offkai_bot.main.calculate_attendance")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_attendance_success(
    mock_log,
    mock_get_event,
    mock_calculate_attendance,
    mock_interaction,
    mock_event_obj,  # From this file
    prepopulated_event_cache,  # Use fixture to ensure cache is populated
):
    """Test the successful path of attendance."""
    # Arrange
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj

    # Mock the data layer function returning attendance data
    mock_total_count = 5
    mock_attendee_list = ["UserA", "UserA +1", "UserB", "UserC", "UserC +1"]
    mock_calculate_attendance.return_value = (mock_total_count, mock_attendee_list)

    # Act
    await main.attendance.callback(
        mock_interaction,
        event_name=event_name_target,
    )

    # Assert
    # 1. Check get_event call
    mock_get_event.assert_called_once_with(event_name_target)
    # 2. Check calculate_attendance call
    mock_calculate_attendance.assert_called_once_with(event_name_target)
    # 3. Check final interaction response with correct formatting
    expected_output = (
        f"**Attendance for {event_name_target}**\n\n"
        f"Total Attendees: **{mock_total_count}**\n\n"
        "1. UserA\n"
        "2. UserA +1\n"
        "3. UserB\n"
        "4. UserC\n"
        "5. UserC +1"
    )
    mock_interaction.response.send_message.assert_awaited_once_with(expected_output, ephemeral=True)
    # 4. Check logs (optional)
    mock_log.warning.assert_not_called()


@patch("offkai_bot.main.calculate_attendance")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_attendance_sort_success(
    mock_log,
    mock_get_event,
    mock_calculate_attendance,
    mock_interaction,
    mock_event_obj,  # From this file
    prepopulated_event_cache,  # Use fixture to ensure cache is populated
):
    """Test the successful path of attendance."""
    # Arrange
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj

    # Mock the data layer function returning attendance data
    mock_total_count = 5
    mock_attendee_list = ["UserC", "UserC +1", "UserA", "UserB", "UserB +1"]
    mock_calculate_attendance.return_value = (mock_total_count, mock_attendee_list)

    # Act
    await main.attendance.callback(
        mock_interaction,
        event_name=event_name_target,
        sort=True,
    )

    # Assert
    # 1. Check get_event call
    mock_get_event.assert_called_once_with(event_name_target)
    # 2. Check calculate_attendance call
    mock_calculate_attendance.assert_called_once_with(event_name_target)
    # 3. Check final interaction response with correct formatting
    expected_output = (
        f"**Attendance for {event_name_target}**\n\n"
        f"Total Attendees: **{mock_total_count}**\n\n"
        "1. UserA\n"
        "2. UserB\n"
        "3. UserB +1\n"
        "4. UserC\n"
        "5. UserC +1"
    )
    mock_interaction.response.send_message.assert_awaited_once_with(expected_output, ephemeral=True)
    # 4. Check logs (optional)
    mock_log.warning.assert_not_called()


@patch("offkai_bot.main.calculate_attendance")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_attendance_success_truncation(
    mock_log, mock_get_event, mock_calculate_attendance, mock_interaction, mock_event_obj, prepopulated_event_cache
):
    """Test attendance output truncation when the list is very long."""
    # Arrange
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj

    # Create a very long list of attendees
    long_attendee_list = [f"User{i:03d}" for i in range(1000)]
    mock_total_count = 100
    mock_calculate_attendance.return_value = (mock_total_count, long_attendee_list)

    # Construct the expected *full* output first to check length
    full_output_list = "\n".join(f"{i + 1}. {name}" for i, name in enumerate(long_attendee_list))
    full_output = (
        f"**Attendance for {event_name_target}**\n\nTotal Attendees: **{mock_total_count}**\n\n{full_output_list}"
    )
    assert len(full_output) > 1900  # Verify our test data causes truncation

    # Construct the expected truncated output
    expected_truncated_output = full_output[:1900] + "\n... (list truncated)"

    # Act
    await main.attendance.callback(
        mock_interaction,
        event_name=event_name_target,
    )

    # Assert
    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_attendance.assert_called_once_with(event_name_target)
    mock_interaction.response.send_message.assert_awaited_once_with(expected_truncated_output, ephemeral=True)


@patch("offkai_bot.main.calculate_attendance")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_attendance_event_not_found(
    mock_log,
    mock_get_event,
    mock_calculate_attendance,
    mock_interaction,
    prepopulated_event_cache,  # Still useful for setup/teardown
):
    """Test attendance when the initial get_event fails."""
    # Arrange
    event_name_target = "NonExistent Event"
    mock_get_event.side_effect = EventNotFoundError(event_name_target)

    # Act & Assert
    with pytest.raises(EventNotFoundError):
        await main.attendance.callback(
            mock_interaction,
            event_name=event_name_target,
        )

    # Assert only get_event was called
    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_attendance.assert_not_called()
    mock_interaction.response.send_message.assert_not_awaited()


@patch("offkai_bot.main.calculate_attendance")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_attendance_no_responses_found(
    mock_log, mock_get_event, mock_calculate_attendance, mock_interaction, mock_event_obj, prepopulated_event_cache
):
    """Test attendance when calculate_attendance raises NoResponsesFoundError."""
    # Arrange
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj
    mock_calculate_attendance.side_effect = NoResponsesFoundError(event_name_target)

    # Act & Assert
    with pytest.raises(NoResponsesFoundError):
        await main.attendance.callback(
            mock_interaction,
            event_name=event_name_target,
        )

    # Assert calls up to calculate_attendance
    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_attendance.assert_called_once_with(event_name_target)

    # Assert subsequent steps were NOT called
    mock_interaction.response.send_message.assert_not_awaited()
