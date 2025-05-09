# tests/commands/test_create_offkai.py

import copy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands

# Import the function to test and relevant errors/classes
from offkai_bot import main
from offkai_bot.alerts.task import CloseOffkaiTask
from offkai_bot.data.event import Event  # To create return value for add_event
from offkai_bot.errors import (
    DuplicateEventError,
    EventDateTimeInPastError,
    EventDeadlineAfterEventError,
    EventDeadlineInPastError,
    EventNotFoundError,  # Needed for mocking get_event side effect
    InvalidChannelTypeError,
    InvalidDateTimeFormatError,
    ThreadCreationError,
)
from offkai_bot.util import JST

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

    # Mock the client instance attached to main
    # We need this because the command callback uses main.client
    with patch("offkai_bot.main.client", new_callable=MagicMock) as mock_client:
        interaction.client = mock_client  # Assign mock client to interaction
        yield interaction  # Yield the interaction with the mocked client

    return interaction


@pytest.fixture
def mock_thread():
    """Fixture for a mock discord.Thread."""
    thread = MagicMock(spec=discord.Thread)
    thread.id = 111222333
    thread.mention = "<#111222333>"
    return thread


# *** Use explicitly future dates in fixture for robustness ***
@pytest.fixture
def mock_created_event():
    """Fixture for a mock Event object returned by add_event."""
    # Use dates clearly in the future relative to typical test execution time
    now = datetime.now(UTC)
    event_dt = now + timedelta(days=30)
    deadline_dt = event_dt - timedelta(days=7)  # Ensure deadline is before event
    return Event(
        event_name="Test Event",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=event_dt,
        event_deadline=deadline_dt,
        channel_id=456,
        thread_id=111222333,
        message_id=None,
        open=True,
        archived=False,
        drinks=["Test Drink"],
        message="Test Announce Msg",
    )


# --- Test Cases ---


# Patches for success tests
@patch("offkai_bot.main.register_deadline_reminders")  # <-- CORRECTED PATCH
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
    mock_register_reminders,  # <-- CORRECTED MOCK ARG
    mock_interaction,
    mock_thread,
    mock_created_event,
):
    """Test the successful path of create_offkai including a deadline."""
    # Arrange
    event_name = mock_created_event.event_name
    venue = mock_created_event.venue
    address = mock_created_event.address
    gmaps = mock_created_event.google_maps_link
    event_dt_jst = mock_created_event.event_datetime.astimezone(JST)
    # Ensure deadline exists before accessing it
    assert mock_created_event.event_deadline is not None
    deadline_dt_jst = mock_created_event.event_deadline.astimezone(JST)
    dt_str = event_dt_jst.strftime(r"%Y-%m-%d %H:%M")
    deadline_str = deadline_dt_jst.strftime(r"%Y-%m-%d %H:%M")
    drinks_str = ", ".join(mock_created_event.drinks)
    announce_msg = mock_created_event.message

    parsed_event_dt = mock_created_event.event_datetime
    parsed_deadline_dt = mock_created_event.event_deadline

    mock_get_event.side_effect = EventNotFoundError(event_name)
    mock_parse_dt.side_effect = [parsed_event_dt, parsed_deadline_dt]
    mock_parse_drinks.return_value = mock_created_event.drinks
    mock_interaction.channel.create_thread.return_value = mock_thread
    mock_add_event.return_value = mock_created_event  # IMPORTANT: Ensure add_event returns the object

    # Act
    await main.create_offkai.callback(
        mock_interaction,
        event_name=event_name,
        venue=venue,
        address=address,
        google_maps_link=gmaps,
        date_time=dt_str,
        deadline=deadline_str,
        drinks=drinks_str,
        announce_msg=announce_msg,
    )

    # Assert
    # ... (previous assertions remain the same) ...
    mock_get_event.assert_called_once_with(event_name)
    assert mock_parse_dt.call_count == 2
    mock_parse_dt.assert_any_call(dt_str)
    mock_parse_dt.assert_any_call(deadline_str)
    mock_parse_drinks.assert_called_once_with(drinks_str)
    mock_validate_ctx.assert_called_once_with(mock_interaction)
    mock_interaction.channel.create_thread.assert_awaited_once_with(
        name=event_name, type=discord.ChannelType.public_thread
    )
    mock_add_event.assert_called_once_with(
        event_name=event_name,
        venue=venue,
        address=address,
        google_maps_link=gmaps,
        event_datetime=parsed_event_dt,
        event_deadline=parsed_deadline_dt,
        channel_id=mock_interaction.channel.id,
        thread_id=mock_thread.id,
        drinks_list=mock_created_event.drinks,
        announce_msg=announce_msg,
    )
    mock_send_msg.assert_awaited_once_with(mock_thread, mock_created_event)
    expected_response = (
        f"# Offkai Created: {event_name}\n\n{announce_msg}\n\nJoin the discussion and RSVP here: {mock_thread.mention}"
    )
    mock_interaction.response.send_message.assert_awaited_once_with(expected_response)
    mock_log.info.assert_called()

    # --- ADD ASSERTION FOR register_deadline_reminders ---
    # Check it was called once with the client and the event object returned by add_event
    mock_register_reminders.assert_called_once_with(mock_interaction.client, mock_created_event)
    # --- END ASSERTION ---


# Replace register_alert patch with register_deadline_reminders
@patch("offkai_bot.main.register_deadline_reminders")  # <-- CORRECTED PATCH
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
    mock_register_reminders,  # <-- CORRECTED MOCK ARG
    mock_interaction,
    mock_thread,
    mock_created_event,
):
    """Test the successful path of create_offkai without providing a deadline."""
    # Arrange
    event_name = "Test Event No Deadline"
    venue = mock_created_event.venue
    address = mock_created_event.address
    gmaps = mock_created_event.google_maps_link
    event_dt_jst = mock_created_event.event_datetime.astimezone(JST)
    dt_str = event_dt_jst.strftime(r"%Y-%m-%d %H:%M")
    drinks_str = ", ".join(mock_created_event.drinks)
    announce_msg = mock_created_event.message

    parsed_event_dt = mock_created_event.event_datetime
    # Create the version of the event that add_event will return
    event_without_deadline = copy.deepcopy(mock_created_event)
    event_without_deadline.event_name = event_name
    event_without_deadline.event_deadline = None

    mock_get_event.side_effect = EventNotFoundError(event_name)
    mock_parse_dt.return_value = parsed_event_dt  # Only called once
    mock_parse_drinks.return_value = mock_created_event.drinks
    mock_interaction.channel.create_thread.return_value = mock_thread
    mock_add_event.return_value = event_without_deadline  # IMPORTANT: Ensure add_event returns this object

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
    # ... (previous assertions remain the same) ...
    mock_get_event.assert_called_once_with(event_name)
    mock_parse_dt.assert_called_once_with(dt_str)
    mock_parse_drinks.assert_called_once_with(drinks_str)
    mock_validate_ctx.assert_called_once_with(mock_interaction)
    mock_interaction.channel.create_thread.assert_awaited_once_with(
        name=event_name, type=discord.ChannelType.public_thread
    )
    mock_add_event.assert_called_once_with(
        event_name=event_name,
        venue=venue,
        address=address,
        google_maps_link=gmaps,
        event_datetime=parsed_event_dt,
        event_deadline=None,
        channel_id=mock_interaction.channel.id,
        thread_id=mock_thread.id,
        drinks_list=mock_created_event.drinks,
        announce_msg=announce_msg,
    )
    mock_send_msg.assert_awaited_once_with(mock_thread, event_without_deadline)
    expected_response = (
        f"# Offkai Created: {event_name}\n\n{announce_msg}\n\nJoin the discussion and RSVP here: {mock_thread.mention}"
    )
    mock_interaction.response.send_message.assert_awaited_once_with(expected_response)
    mock_log.info.assert_called()

    # --- ADD ASSERTION FOR register_deadline_reminders ---
    # Check it was called once with the client and the event object returned by add_event
    mock_register_reminders.assert_called_once_with(
        mock_interaction.client,
        event_without_deadline,  # Check the correct event object was passed
    )
    # --- END ASSERTION ---


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
            date_time="3000-01-01 10:00",  # Other args don't matter much here
        )

    assert exc_info.value.event_name == event_name
    mock_get_event.assert_called_once_with(event_name)
    # Ensure later steps like thread creation weren't called
    mock_interaction.channel.create_thread.assert_not_awaited()


@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main.parse_event_datetime")
@patch("offkai_bot.main._log")
async def test_create_offkai_invalid_datetime_format(mock_log, mock_parse_dt, mock_get_event, mock_interaction):
    """Test create_offkai with an invalid date/time string format."""
    # Arrange
    event_name = "DateTime Format Test"
    invalid_dt_str = "invalid-date"
    mock_get_event.side_effect = EventNotFoundError(event_name)
    mock_parse_dt.side_effect = InvalidDateTimeFormatError()

    # Act & Assert
    with pytest.raises(InvalidDateTimeFormatError):
        await main.create_offkai.callback(
            mock_interaction,
            event_name=event_name,
            venue="Any",
            address="Any",
            google_maps_link="Any",
            date_time=invalid_dt_str,
            deadline="3000-01-01 11:00",  # Provide a deadline, but it shouldn't be parsed
        )

    mock_get_event.assert_called_once_with(event_name)
    mock_parse_dt.assert_called_once_with(invalid_dt_str)
    mock_interaction.channel.create_thread.assert_not_awaited()


@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main.parse_event_datetime")
@patch("offkai_bot.main._log")
async def test_create_offkai_invalid_deadline_format(mock_log, mock_parse_dt, mock_get_event, mock_interaction):
    """Test create_offkai with an invalid deadline string format."""
    # Arrange
    event_name = "Deadline Format Test"
    valid_dt_str = "2025-08-01 19:00"
    invalid_deadline_str = "invalid-deadline"
    # Need a valid datetime object for the first parse call
    parsed_event_dt = (datetime.now(UTC) + timedelta(days=60)).replace(tzinfo=UTC)

    mock_get_event.side_effect = EventNotFoundError(event_name)
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
            deadline=invalid_deadline_str,
        )

    mock_get_event.assert_called_once_with(event_name)
    assert mock_parse_dt.call_count == 2
    mock_parse_dt.assert_any_call(valid_dt_str)
    mock_parse_dt.assert_any_call(invalid_deadline_str)
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
            date_time="3000-01-01 10:00",
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
    mock_parse_dt.return_value = datetime.strptime("3000-01-01 10:00", r"%Y-%m-%d %H:%M").replace(tzinfo=JST)
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
            date_time="3000-01-01 10:00",
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


@pytest.mark.parametrize(
    "validation_error_type",
    [
        EventDateTimeInPastError,
        EventDeadlineInPastError,
        EventDeadlineAfterEventError,
    ],
)
@patch("offkai_bot.main.send_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.add_event")  # Mock add_event to raise the error
@patch("offkai_bot.main.validate_interaction_context")
@patch("offkai_bot.main.parse_drinks")
@patch("offkai_bot.main.parse_event_datetime")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_create_offkai_add_event_validation_fails(
    mock_log,
    mock_get_event,
    mock_parse_dt,
    mock_parse_drinks,
    mock_validate_ctx,
    mock_add_event,  # This mock will raise the error
    mock_send_msg,
    mock_interaction,
    mock_thread,
    mock_created_event,  # Use fixture for valid parsed dates
    validation_error_type,  # Parameter for the error type
):
    """Test create_offkai when add_event raises a datetime validation error."""
    # Arrange
    event_name = "Validation Fail Event"
    venue = "V"
    address = "A"
    gmaps = "G"
    # Use valid future date strings corresponding to mock_created_event
    event_dt_jst = mock_created_event.event_datetime.astimezone(JST)
    deadline_dt_jst = mock_created_event.event_deadline.astimezone(JST)
    dt_str = event_dt_jst.strftime(r"%Y-%m-%d %H:%M")
    deadline_str = deadline_dt_jst.strftime(r"%Y-%m-%d %H:%M")
    drinks_str = "D"
    announce_msg = "Msg"

    # Setup mocks for steps *before* add_event
    mock_get_event.side_effect = EventNotFoundError(event_name)
    # Ensure parsing returns valid future dates from fixture
    mock_parse_dt.side_effect = [mock_created_event.event_datetime, mock_created_event.event_deadline]
    mock_parse_drinks.return_value = ["D"]
    mock_validate_ctx.return_value = None
    mock_interaction.channel.create_thread.return_value = mock_thread

    # Configure add_event to raise the specific validation error
    mock_add_event.side_effect = validation_error_type()

    # Act & Assert
    with pytest.raises(validation_error_type):
        await main.create_offkai.callback(
            mock_interaction,
            event_name=event_name,
            venue=venue,
            address=address,
            google_maps_link=gmaps,
            date_time=dt_str,
            deadline=deadline_str,
            drinks=drinks_str,
            announce_msg=announce_msg,
        )

    # Assert steps *before* add_event were called
    mock_get_event.assert_called_once_with(event_name)
    assert mock_parse_dt.call_count == 2
    mock_parse_drinks.assert_called_once_with(drinks_str)
    mock_validate_ctx.assert_called_once_with(mock_interaction)
    mock_interaction.channel.create_thread.assert_awaited_once_with(
        name=event_name, type=discord.ChannelType.public_thread
    )
    # Assert add_event was called (and raised the error)
    mock_add_event.assert_called_once()

    # Assert steps *after* add_event were NOT called
    mock_send_msg.assert_not_awaited()
    mock_interaction.response.send_message.assert_not_awaited()
