# tests/commands/test_modify_offkai.py

import copy
import logging
from datetime import UTC, datetime
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands

# Import the function to test and relevant errors/classes
from offkai_bot import main
from offkai_bot.data.event import Event  # To create return value
from offkai_bot.errors import (
    EventArchivedError,
    EventNotFoundError,
    InvalidDateTimeFormatError,
    MissingChannelIDError,
    NoChangesProvidedError,
    ThreadAccessError,
    ThreadNotFoundError,
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
    interaction.command.name = "modify_offkai"

    # Mock response methods
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    # Add client mock needed by fetch_thread_for_event
    interaction.client = MagicMock(spec=discord.Client)
    # Mock fetch_channel on client as well (might be used depending on context)
    interaction.client.fetch_channel = AsyncMock()

    return interaction


@pytest.fixture
def mock_modified_event():
    """Fixture for the expected state of the event after modification (including deadline)."""
    # Based on "Summer Bash" being modified
    return Event(
        event_name="Summer Bash",
        venue="New Venue",  # Modified
        address="1 Beach Rd",
        google_maps_link="new_gmap",  # Modified
        event_datetime=datetime(2024, 8, 10, 20, 0, tzinfo=UTC),  # Modified
        event_deadline=datetime(2024, 8, 5, 23, 59, tzinfo=UTC),  # Modified deadline
        channel_id=1001,  # From sample_event_list
        thread_id=1501,  # From sample_event_list
        message_id=2001,  # From sample_event_list
        open=True,
        archived=False,
        drinks=["Water"],  # Modified
        message=None,  # Assume message wasn't part of modification
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
    event_name_to_modify = "Summer Bash"  # Exists in prepopulated_event_cache
    update_text = "Details updated!"
    new_venue = "New Venue"
    new_gmaps = "new_gmap"
    new_dt_str = "2024-08-10 20:00"
    new_deadline_str = "2024-08-05 23:59"  # Add deadline string
    new_drinks_str = "Water"

    # Ensure the mock returns the event with the modified deadline
    mock_update_details.return_value = mock_modified_event
    mock_fetch_thread.return_value = mock_thread
    # Ensure thread ID matches event's thread ID for consistency
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
        deadline=new_deadline_str,  # Pass the deadline string
        drinks=new_drinks_str,
    )

    # Assert
    # 1. Check update_event_details call (includes deadline_str)
    mock_update_details.assert_called_once_with(
        event_name=event_name_to_modify,
        venue=new_venue,
        address=None,
        google_maps_link=new_gmaps,
        date_time_str=new_dt_str,
        deadline_str=new_deadline_str,  # Verify deadline is passed
        drinks_str=new_drinks_str,
    )
    # 2. Check save data
    mock_save_data.assert_called_once()
    # 3. Check update original message/view
    mock_update_msg_view.assert_awaited_once_with(ANY, mock_modified_event)
    # 4. Check fetching the thread via helper
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_modified_event)
    # 5. Check sending update message to thread
    mock_thread.send.assert_awaited_once_with(f"**Event Updated:**\n{update_text}")
    # 6. Check final interaction response
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


@pytest.mark.parametrize(
    "error_type, error_args",
    [
        (EventNotFoundError, ("NonExistent Event",)),
        (EventArchivedError, ("Archived Party", "modify")),  # Use event from sample_event_list
        (InvalidDateTimeFormatError, ()),  # Error raised during parsing
        (NoChangesProvidedError, ()),  # Error raised if no changes detected
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
            deadline="2024-12-12 12:00",  # Include deadline in call
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
