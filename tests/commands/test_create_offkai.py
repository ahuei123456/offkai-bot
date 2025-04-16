# tests/commands/test_create_offkai.py

import copy
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands

# Import the function to test and relevant errors/classes
from offkai_bot import main
from offkai_bot.data.event import Event  # To create return value for add_event
from offkai_bot.errors import (
    DuplicateEventError,
    EventNotFoundError,  # Needed for mocking get_event side effect
    InvalidChannelTypeError,
    InvalidDateTimeFormatError,
    ThreadCreationError,
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
    interaction.command.name = "create_offkai"

    # Mock response methods
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    return interaction


@pytest.fixture
def mock_thread():
    """Fixture for a mock discord.Thread."""
    thread = MagicMock(spec=discord.Thread)
    thread.id = 111222333
    thread.mention = "<#111222333>"
    return thread


@pytest.fixture
def mock_created_event():
    """Fixture for a mock Event object returned by add_event."""
    # Use timezone-aware UTC datetimes
    event_dt = datetime(2024, 8, 1, 19, 0, tzinfo=UTC)
    deadline_dt = datetime(2024, 7, 25, 23, 59, tzinfo=UTC)
    return Event(
        event_name="Test Event",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=event_dt,
        event_deadline=deadline_dt,  # Add deadline
        channel_id=456,  # Match mock_interaction.channel.id
        thread_id=111222333,  # Match mock_thread.id
        message_id=None,
        open=True,
        archived=False,
        drinks=["Test Drink"],
        message="Test Announce Msg",
    )


# --- Test Cases ---


@patch("offkai_bot.main.send_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.add_event")
@patch("offkai_bot.main.validate_interaction_context")
@patch("offkai_bot.main.parse_drinks")
@patch("offkai_bot.main.parse_event_datetime")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_create_offkai_success(
    mock_log,
    mock_get_event,
    mock_parse_dt,
    mock_parse_drinks,
    mock_validate_ctx,
    mock_add_event,
    mock_send_msg,
    mock_interaction,
    mock_thread,
    mock_created_event,
):
    """Test the successful path of create_offkai including a deadline."""
    # Arrange
    event_name = "Test Event"
    venue = "Test Venue"
    address = "Test Address"
    gmaps = "test_link"
    dt_str = "2024-08-01 19:00"
    deadline_str = "2024-07-25 23:59"  # Add deadline input
    drinks_str = "Test Drink"
    announce_msg = "Test Announce Msg"

    # Define expected parsed datetimes (use the ones from the updated fixture)
    parsed_event_dt = mock_created_event.event_datetime
    parsed_deadline_dt = mock_created_event.event_deadline

    mock_get_event.side_effect = EventNotFoundError(event_name)
    # parse_event_datetime will be called twice: once for date_time, once for deadline
    mock_parse_dt.side_effect = [parsed_event_dt, parsed_deadline_dt]
    mock_parse_drinks.return_value = ["Test Drink"]
    mock_interaction.channel.create_thread.return_value = mock_thread
    mock_add_event.return_value = mock_created_event

    # Act
    await main.create_offkai.callback(
        mock_interaction,
        event_name=event_name,
        venue=venue,
        address=address,
        google_maps_link=gmaps,
        date_time=dt_str,
        deadline=deadline_str,  # Pass the deadline string
        drinks=drinks_str,
        announce_msg=announce_msg,
    )

    # Assert
    # 1. Check duplicate check
    mock_get_event.assert_called_once_with(event_name)
    # 2. Check parsing
    assert mock_parse_dt.call_count == 2
    mock_parse_dt.assert_any_call(dt_str)
    mock_parse_dt.assert_any_call(deadline_str)
    mock_parse_drinks.assert_called_once_with(drinks_str)
    # 3. Check context validation
    mock_validate_ctx.assert_called_once_with(mock_interaction)
    # 4. Check thread creation
    mock_interaction.channel.create_thread.assert_awaited_once_with(
        name=event_name, type=discord.ChannelType.public_thread
    )
    # 5. Check event addition to data layer (including event_deadline)
    mock_add_event.assert_called_once_with(
        event_name=event_name,
        venue=venue,
        address=address,
        google_maps_link=gmaps,
        event_datetime=parsed_event_dt,
        event_deadline=parsed_deadline_dt,  # Verify deadline is passed
        channel_id=mock_interaction.channel.id,
        thread_id=mock_thread.id,
        drinks_list=mock_parse_drinks.return_value,
        announce_msg=announce_msg,
    )
    # 6. Check message sending to thread
    mock_send_msg.assert_awaited_once_with(mock_thread, mock_created_event)
    # 7. Check final response to interaction
    expected_response = (
        f"# Offkai Created: {event_name}\n\n{announce_msg}\n\nJoin the discussion and RSVP here: {mock_thread.mention}"
    )
    mock_interaction.response.send_message.assert_awaited_once_with(expected_response)
    # 8. Check logs (optional)
    mock_log.info.assert_called()


@patch("offkai_bot.main.send_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.add_event")
@patch("offkai_bot.main.validate_interaction_context")
@patch("offkai_bot.main.parse_drinks")
@patch("offkai_bot.main.parse_event_datetime")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_create_offkai_success_without_deadline(
    mock_log,
    mock_get_event,
    mock_parse_dt,
    mock_parse_drinks,
    mock_validate_ctx,
    mock_add_event,
    mock_send_msg,
    mock_interaction,
    mock_thread,
    mock_created_event,  # Use the fixture, but we'll assert None for deadline
):
    """Test the successful path of create_offkai without providing a deadline."""
    # Arrange
    event_name = "Test Event No Deadline"
    venue = "Test Venue"
    address = "Test Address"
    gmaps = "test_link"
    dt_str = "2024-08-01 19:00"
    # deadline_str is None
    drinks_str = "Test Drink"
    announce_msg = "Test Announce Msg"

    # Define expected parsed datetime (use the one from the fixture)
    parsed_event_dt = mock_created_event.event_datetime
    # Create a version of the event object with deadline=None for assertion
    event_without_deadline = copy.deepcopy(mock_created_event)
    event_without_deadline.event_name = event_name  # Match name
    event_without_deadline.event_deadline = None

    mock_get_event.side_effect = EventNotFoundError(event_name)
    # parse_event_datetime will be called only once for date_time
    mock_parse_dt.return_value = parsed_event_dt
    mock_parse_drinks.return_value = ["Test Drink"]
    mock_interaction.channel.create_thread.return_value = mock_thread
    mock_add_event.return_value = event_without_deadline  # Return the version without deadline

    # Act
    await main.create_offkai.callback(
        mock_interaction,
        event_name=event_name,
        venue=venue,
        address=address,
        google_maps_link=gmaps,
        date_time=dt_str,
        deadline=None,  # Explicitly pass None
        drinks=drinks_str,
        announce_msg=announce_msg,
    )

    # Assert
    # 1. Check duplicate check
    mock_get_event.assert_called_once_with(event_name)
    # 2. Check parsing
    mock_parse_dt.assert_called_once_with(dt_str)  # Called only once
    mock_parse_drinks.assert_called_once_with(drinks_str)
    # 3. Check context validation
    mock_validate_ctx.assert_called_once_with(mock_interaction)
    # 4. Check thread creation
    mock_interaction.channel.create_thread.assert_awaited_once_with(
        name=event_name, type=discord.ChannelType.public_thread
    )
    # 5. Check event addition to data layer (event_deadline should be None)
    mock_add_event.assert_called_once_with(
        event_name=event_name,
        venue=venue,
        address=address,
        google_maps_link=gmaps,
        event_datetime=parsed_event_dt,
        event_deadline=None,  # Verify deadline is None
        channel_id=mock_interaction.channel.id,
        thread_id=mock_thread.id,
        drinks_list=mock_parse_drinks.return_value,
        announce_msg=announce_msg,
    )
    # 6. Check message sending to thread
    mock_send_msg.assert_awaited_once_with(mock_thread, event_without_deadline)
    # 7. Check final response to interaction
    expected_response = (
        f"# Offkai Created: {event_name}\n\n{announce_msg}\n\nJoin the discussion and RSVP here: {mock_thread.mention}"
    )
    mock_interaction.response.send_message.assert_awaited_once_with(expected_response)
    # 8. Check logs (optional)
    mock_log.info.assert_called()


@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_create_offkai_duplicate_event(mock_log, mock_get_event, mock_interaction):
    """Test create_offkai when the event name already exists."""
    # Arrange
    event_name = "Existing Event"
    mock_existing_event = MagicMock(spec=Event)  # Just need an object to be returned
    mock_get_event.return_value = mock_existing_event  # Simulate event found

    # Act & Assert
    with pytest.raises(DuplicateEventError) as exc_info:
        await main.create_offkai.callback(
            mock_interaction,
            event_name=event_name,
            venue="Any",
            address="Any",
            google_maps_link="Any",
            date_time="2024-01-01 10:00",  # Other args don't matter much here
        )

    assert exc_info.value.event_name == event_name
    mock_get_event.assert_called_once_with(event_name)
    # Ensure later steps like thread creation weren't called
    mock_interaction.channel.create_thread.assert_not_awaited()


@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main.parse_event_datetime")
@patch("offkai_bot.main._log")
async def test_create_offkai_invalid_datetime(mock_log, mock_parse_dt, mock_get_event, mock_interaction):
    """Test create_offkai with an invalid date/time string."""
    # Arrange
    event_name = "DateTime Test"
    invalid_dt_str = "invalid-date"
    mock_get_event.side_effect = EventNotFoundError(event_name)  # Simulate event not found
    mock_parse_dt.side_effect = InvalidDateTimeFormatError()  # Simulate parsing failure

    # Act & Assert
    with pytest.raises(InvalidDateTimeFormatError):
        await main.create_offkai.callback(
            mock_interaction,
            event_name=event_name,
            venue="Any",
            address="Any",
            google_maps_link="Any",
            date_time=invalid_dt_str,
        )

    mock_get_event.assert_called_once_with(event_name)
    mock_parse_dt.assert_called_once_with(invalid_dt_str)
    # Ensure later steps weren't called
    mock_interaction.channel.create_thread.assert_not_awaited()


@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main.parse_event_datetime")
@patch("offkai_bot.main._log")
async def test_create_offkai_invalid_deadline(mock_log, mock_parse_dt, mock_get_event, mock_interaction):
    """Test create_offkai with an invalid deadline string."""
    # Arrange
    event_name = "Deadline Test"
    valid_dt_str = "2024-08-01 19:00"
    invalid_deadline_str = "invalid-deadline"
    parsed_event_dt = datetime(2024, 8, 1, 19, 0, tzinfo=UTC)

    mock_get_event.side_effect = EventNotFoundError(event_name)
    # Make the *first* call succeed, but the *second* call (for deadline) fail
    mock_parse_dt.side_effect = [parsed_event_dt, InvalidDateTimeFormatError()]

    # Act & Assert
    with pytest.raises(InvalidDateTimeFormatError):
        await main.create_offkai.callback(
            mock_interaction,
            event_name=event_name,
            venue="Any",
            address="Any",
            google_maps_link="Any",
            date_time=valid_dt_str,
            deadline=invalid_deadline_str,  # Pass the invalid deadline
        )

    mock_get_event.assert_called_once_with(event_name)
    # Check parse_event_datetime was called twice
    assert mock_parse_dt.call_count == 2
    mock_parse_dt.assert_any_call(valid_dt_str)
    mock_parse_dt.assert_any_call(invalid_deadline_str)
    # Ensure later steps weren't called
    mock_interaction.channel.create_thread.assert_not_awaited()


@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main.parse_event_datetime")
@patch("offkai_bot.main.parse_drinks")
@patch("offkai_bot.main.validate_interaction_context")
@patch("offkai_bot.main._log")
async def test_create_offkai_invalid_context(
    mock_log, mock_validate_ctx, mock_parse_drinks, mock_parse_dt, mock_get_event, mock_interaction
):
    """Test create_offkai when used in an invalid context (e.g., DM)."""
    # Arrange
    event_name = "Context Test"
    mock_get_event.side_effect = EventNotFoundError(event_name)
    mock_parse_dt.return_value = datetime.now()  # Assume parsing succeeds
    mock_parse_drinks.return_value = []
    mock_validate_ctx.side_effect = InvalidChannelTypeError()  # Simulate context validation failure

    # Act & Assert
    with pytest.raises(InvalidChannelTypeError):
        await main.create_offkai.callback(
            mock_interaction,
            event_name=event_name,
            venue="Any",
            address="Any",
            google_maps_link="Any",
            date_time="2024-01-01 10:00",
        )

    mock_get_event.assert_called_once_with(event_name)
    mock_parse_dt.assert_called_once()
    mock_parse_drinks.assert_called_once()
    mock_validate_ctx.assert_called_once_with(mock_interaction)
    # Ensure later steps weren't called
    mock_interaction.channel.create_thread.assert_not_awaited()


@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main.parse_event_datetime")
@patch("offkai_bot.main.parse_drinks")
@patch("offkai_bot.main.validate_interaction_context")
@patch("offkai_bot.main._log")
async def test_create_offkai_thread_creation_fails(
    mock_log, mock_validate_ctx, mock_parse_drinks, mock_parse_dt, mock_get_event, mock_interaction
):
    """Test create_offkai when thread creation raises an HTTP exception."""
    # Arrange
    event_name = "Thread Fail Test"
    mock_get_event.side_effect = EventNotFoundError(event_name)
    mock_parse_dt.return_value = datetime.now()
    mock_parse_drinks.return_value = []
    mock_validate_ctx.return_value = None  # Assume context is valid
    # Simulate discord API error during thread creation
    discord_error = discord.HTTPException(MagicMock(), "Mock Discord Error")
    mock_interaction.channel.create_thread.side_effect = discord_error

    # Act & Assert
    with pytest.raises(ThreadCreationError) as exc_info:
        await main.create_offkai.callback(
            mock_interaction,
            event_name=event_name,
            venue="Any",
            address="Any",
            google_maps_link="Any",
            date_time="2024-01-01 10:00",
        )

    # Check the custom error details
    assert exc_info.value.event_name == event_name
    assert exc_info.value.original_exception is discord_error

    # Check that steps up to thread creation were called
    mock_get_event.assert_called_once_with(event_name)
    mock_parse_dt.assert_called_once()
    mock_parse_drinks.assert_called_once()
    mock_validate_ctx.assert_called_once_with(mock_interaction)
    mock_interaction.channel.create_thread.assert_awaited_once()

    # Check logging
    mock_log.error.assert_called_once()
    assert f"Failed to create thread for '{event_name}'" in mock_log.error.call_args[0][0]

    # Ensure later steps (add_event, send_message, response) weren't called
    # (Need to import add_event and send_event_message mocks if checking them)
    # mock_add_event.assert_not_called()
    # mock_send_msg.assert_not_awaited()
    mock_interaction.response.send_message.assert_not_awaited()
