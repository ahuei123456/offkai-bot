# tests/commands/test_modify_offkai.py

import copy
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands

# Import the function to test and relevant errors/classes
from offkai_bot import main
from offkai_bot.data.event import Event  # To create return value
from offkai_bot.errors import (
    EventArchivedError,
    EventDateTimeInPastError,
    EventDeadlineAfterEventError,
    EventDeadlineInPastError,
    EventNotFoundError,
    InvalidDateTimeFormatError,
    MissingChannelIDError,
    NoChangesProvidedError,
    ThreadAccessError,
    ThreadNotFoundError,
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
    interaction.command.name = "modify_offkai"

    # Mock response methods
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    # Add client mock needed by fetch_thread_for_event
    interaction.client = MagicMock(spec=discord.Client)
    # Mock fetch_channel on client as well (might be used depending on context)
    interaction.client.fetch_channel = AsyncMock()

    return interaction


# *** Use explicitly future dates in fixture for robustness ***
@pytest.fixture
def mock_modified_event():
    """Fixture for the expected state of the event after modification."""
    now = datetime.now(UTC)
    event_dt = now + timedelta(days=40)  # Further in future
    deadline_dt = event_dt - timedelta(days=10)  # Also future, before event
    return Event(
        event_name="Summer Bash",  # Matches sample_event_list[0]
        venue="New Venue",
        address="1 Beach Rd",  # Original address
        google_maps_link="new_gmap",
        event_datetime=event_dt,
        event_deadline=deadline_dt,
        channel_id=1001,
        thread_id=1501,
        message_id=2001,
        open=True,
        archived=False,
        drinks=["Water"],
        message=None,
    )


# --- Test Cases ---


@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main._log")
async def test_modify_offkai_success(
    mock_log,
    mock_update_details,
    mock_save_data,
    mock_update_msg_view,  # Renamed from mock_update_msg
    mock_fetch_thread,  # Renamed from mock_client
    mock_interaction,
    mock_thread,  # From conftest.py
    mock_modified_event,  # From this file
    prepopulated_event_cache,
):
    """Test the successful path of modify_offkai including updating the deadline."""
    # Arrange
    event_name_to_modify = "Summer Bash"
    update_text = "Details updated!"
    new_venue = mock_modified_event.venue
    new_gmaps = mock_modified_event.google_maps_link
    # Generate date strings based on the fixture's future dates
    event_dt_jst = mock_modified_event.event_datetime.astimezone(JST)
    deadline_dt_jst = mock_modified_event.event_deadline.astimezone(JST)
    new_dt_str = event_dt_jst.strftime(r"%Y-%m-%d %H:%M")
    new_deadline_str = deadline_dt_jst.strftime(r"%Y-%m-%d %H:%M")
    new_drinks_str = ", ".join(mock_modified_event.drinks)

    mock_update_details.return_value = mock_modified_event
    mock_fetch_thread.return_value = mock_thread
    mock_thread.id = mock_modified_event.thread_id
    mock_thread.mention = f"<#{mock_thread.id}>"

    # Act
    await main.modify_offkai.callback(
        mock_interaction,
        event_name=event_name_to_modify,
        update_msg=update_text,
        venue=new_venue,
        address=None,
        google_maps_link=new_gmaps,
        date_time=new_dt_str,
        deadline=new_deadline_str,
        drinks=new_drinks_str,
    )

    # Assert
    mock_update_details.assert_called_once_with(
        event_name=event_name_to_modify,
        venue=new_venue,
        address=None,
        google_maps_link=new_gmaps,
        date_time_str=new_dt_str,
        deadline_str=new_deadline_str,
        drinks_str=new_drinks_str,
    )
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once_with(ANY, mock_modified_event)
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_modified_event)
    mock_thread.send.assert_awaited_once_with(f"**Event Updated:**\n{update_text}")
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )
    mock_log.warning.assert_not_called()
    mock_log.error.assert_not_called()


@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main._log")
async def test_modify_offkai_success_without_deadline_change(  # New test
    mock_log,
    mock_update_details,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_interaction,
    mock_thread,
    mock_modified_event,  # Use fixture, but deadline won't change
    prepopulated_event_cache,
):
    """Test the successful path of modify_offkai without changing the deadline."""
    # Arrange
    event_name_to_modify = "Summer Bash"
    update_text = "Venue updated!"
    new_venue = "New Venue Only"

    # Create a version of the modified event where deadline is NOT changed
    # Start from the original event in the cache
    original_event = next(e for e in prepopulated_event_cache if e.event_name == event_name_to_modify)
    event_after_update = copy.deepcopy(original_event)
    event_after_update.venue = new_venue  # Only venue changes

    mock_update_details.return_value = event_after_update  # Return the object with only venue changed
    mock_fetch_thread.return_value = mock_thread
    mock_thread.id = event_after_update.thread_id
    mock_thread.mention = f"<#{mock_thread.id}>"

    # Act
    await main.modify_offkai.callback(
        mock_interaction,
        event_name=event_name_to_modify,
        update_msg=update_text,
        venue=new_venue,
        address=None,
        google_maps_link=None,
        date_time=None,
        deadline=None,  # Explicitly pass None for deadline
        drinks=None,
    )

    # Assert
    # 1. Check update_event_details call (deadline_str is None)
    mock_update_details.assert_called_once_with(
        event_name=event_name_to_modify,
        venue=new_venue,
        address=None,
        google_maps_link=None,
        date_time_str=None,
        deadline_str=None,  # Verify deadline is None
        drinks_str=None,
    )
    # 2. Check save data
    mock_save_data.assert_called_once()
    # 3. Check update original message/view
    mock_update_msg_view.assert_awaited_once_with(ANY, event_after_update)
    # 4. Check fetching the thread via helper
    mock_fetch_thread.assert_awaited_once_with(ANY, event_after_update)
    # 5. Check sending update message to thread
    mock_thread.send.assert_awaited_once_with(f"**Event Updated:**\n{update_text}")
    # 6. Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )
    mock_log.warning.assert_not_called()
    mock_log.error.assert_not_called()


# *** NEW TEST for assigning missing channel_id ***
@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main._log")
async def test_modify_offkai_assigns_channel_id_if_missing(
    mock_log,
    mock_update_details,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_interaction,  # Use the fixture
    mock_thread,
    prepopulated_event_cache,  # To get an event to modify
):
    """Test modify_offkai assigns interaction channel ID if event.channel_id is None."""
    # Arrange
    event_name_to_modify = "Summer Bash"  # Choose an event
    update_text = "Assigning Channel ID test"
    interaction_channel_id = mock_interaction.channel.id  # Get ID from fixture

    # Get the original event and create a copy returned by update_details *without* channel_id
    original_event = next(e for e in prepopulated_event_cache if e.event_name == event_name_to_modify)
    event_returned_by_update = copy.deepcopy(original_event)
    event_returned_by_update.channel_id = None  # Simulate missing ID
    event_returned_by_update.venue = "Slight Change Venue"  # Make some change

    # Configure mocks
    mock_update_details.return_value = event_returned_by_update  # Return the object needing ID assignment
    mock_fetch_thread.return_value = mock_thread  # Assume thread fetch succeeds after ID is assigned
    mock_thread.id = event_returned_by_update.thread_id  # Match thread ID

    # Act
    await main.modify_offkai.callback(
        mock_interaction,
        event_name=event_name_to_modify,
        update_msg=update_text,
        venue=event_returned_by_update.venue,  # Pass the change
    )

    # Assert
    mock_update_details.assert_called_once()  # Verify update was called

    # Verify the log message for assignment
    mock_log.info.assert_any_call(
        f"Assigned current channel ID ({interaction_channel_id}) to event '{event_name_to_modify}' as it was missing."
    )

    mock_save_data.assert_called_once()  # Verify save was called

    # Verify update_event_message was called with the modified object
    # The object passed is the same one modified in place by the command
    mock_update_msg_view.assert_awaited_once_with(ANY, event_returned_by_update)
    # Explicitly check the ID on the object *after* the call
    assert event_returned_by_update.channel_id == interaction_channel_id

    # Verify fetch_thread_for_event was called with the modified object
    mock_fetch_thread.assert_awaited_once_with(ANY, event_returned_by_update)
    # ID check again (redundant but safe)
    assert event_returned_by_update.channel_id == interaction_channel_id

    # Verify thread message was sent
    mock_thread.send.assert_awaited_once_with(f"**Event Updated:**\n{update_text}")

    # Verify final response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )


# *** END NEW TEST ***


@pytest.mark.parametrize(
    "error_type, error_args",
    [
        (EventNotFoundError, ("NonExistent Event",)),
        (EventArchivedError, ("Archived Party", "modify")),
        (InvalidDateTimeFormatError, ()),  # Error from parsing
        (NoChangesProvidedError, ()),
        (EventDateTimeInPastError, ()),  # New validation error
        (EventDeadlineInPastError, ()),  # New validation error
        (EventDeadlineAfterEventError, ()),  # New validation error
    ],
)
# Patches updated to include fetch_thread_for_event
@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main._log")
async def test_modify_offkai_data_layer_errors(
    mock_log,
    mock_update_details,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,  # Include new patch
    mock_interaction,
    error_type,
    error_args,
    prepopulated_event_cache,  # Use fixture to ensure events exist for errors
):
    """Test handling of errors raised by update_event_details."""
    # Arrange
    # Use the event name from error_args if provided, otherwise default
    event_name = error_args[0] if error_args else "Summer Bash"
    mock_update_details.side_effect = error_type(*error_args)

    # Act & Assert
    with pytest.raises(error_type):
        await main.modify_offkai.callback(
            mock_interaction,
            event_name=event_name,
            update_msg="Update attempt",
            venue="Attempt Venue",  # Provide some change to trigger update_details
            deadline="3000-12-12 12:00",  # Include deadline in call
        )

    # Assert update_details was called
    mock_update_details.assert_called_once()
    # Assert subsequent steps were NOT called/awaited
    mock_save_data.assert_not_called()
    mock_update_msg_view.assert_not_awaited()
    mock_fetch_thread.assert_not_awaited()  # Check helper wasn't called
    mock_interaction.response.send_message.assert_not_awaited()


# Test handling errors from fetch_thread_for_event
@pytest.mark.parametrize(
    "fetch_error_type, fetch_error_args_indices, expected_log_level, log_msg_part",
    [
        (ThreadNotFoundError, (0, 4), logging.WARNING, "Could not find thread channel"),
        (MissingChannelIDError, (0,), logging.WARNING, "does not have a channel ID"),
        (ThreadAccessError, (0, 4), logging.ERROR, "Bot lacks permissions"),
    ],
)
@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main._log")
async def test_modify_offkai_fetch_thread_errors(
    mock_log,
    mock_update_details,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_interaction,
    mock_modified_event,  # Use the modified event state
    prepopulated_event_cache,
    fetch_error_type,
    fetch_error_args_indices,
    expected_log_level,
    log_msg_part,
):
    """Test modify_offkai when fetch_thread_for_event raises various errors."""
    # Arrange
    event_name_to_modify = mock_modified_event.event_name
    update_text = "Details updated!"

    # Ensure update_details returns the event object successfully
    mock_update_details.return_value = mock_modified_event

    # Construct error arguments dynamically based on the modified event
    error_args = []
    if 0 in fetch_error_args_indices:
        error_args.append(mock_modified_event.event_name)
    if 4 in fetch_error_args_indices:  # Assuming index 4 corresponds to channel_id/thread_id
        error_args.append(mock_modified_event.thread_id)  # Use thread_id

    # Mock the helper raising the specific error
    mock_fetch_thread.side_effect = fetch_error_type(*error_args)

    # Act
    await main.modify_offkai.callback(
        mock_interaction,
        event_name=event_name_to_modify,
        update_msg=update_text,
        venue="New Venue",  # Provide some change
    )

    # Assert
    # Steps up to fetching thread should succeed
    mock_update_details.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once_with(ANY, mock_modified_event)
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_modified_event)

    # Sending update message to thread should be skipped, log checked
    mock_log.log.assert_called_once()
    log_call = mock_log.log.call_args[0]
    assert log_call[0] == expected_log_level  # Check log level
    assert f"Could not send update message for event '{event_name_to_modify}'" in log_call[1]
    assert log_msg_part in log_call[1]  # Check specific error reason

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )


@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main._log")
async def test_modify_offkai_send_update_fails(
    mock_log,
    mock_update_details,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_interaction,
    mock_thread,  # Need the thread mock here
    mock_modified_event,
    prepopulated_event_cache,
):
    """Test modify_offkai when sending the update message fails."""
    # Arrange
    event_name_to_modify = mock_modified_event.event_name
    update_text = "Details updated!"
    mock_update_details.return_value = mock_modified_event
    # Mock helper returning thread successfully
    mock_fetch_thread.return_value = mock_thread
    mock_thread.id = mock_modified_event.thread_id  # Match ID
    # Simulate error sending message
    send_error = discord.HTTPException(MagicMock(), "Cannot send messages")
    mock_thread.send.side_effect = send_error

    # Act
    await main.modify_offkai.callback(
        mock_interaction,
        event_name=event_name_to_modify,
        update_msg=update_text,
        venue="New Venue",  # Provide some change
    )

    # Assert
    mock_update_details.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_modified_event)
    # Assert send was called
    mock_thread.send.assert_awaited_once_with(f"**Event Updated:**\n{update_text}")

    # Warning should be logged for send failure
    mock_log.warning.assert_called_once()
    assert f"Could not send update message to thread {mock_thread.id}" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )
