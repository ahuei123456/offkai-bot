# tests/commands/test_modify_offkai.py

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

    return interaction


@pytest.fixture
def mock_modified_event():
    """Fixture for the expected state of the event after modification."""
    # Based on "Summer Bash" being modified
    return Event(
        event_name="Summer Bash",
        venue="New Venue",  # Modified
        address="1 Beach Rd",
        google_maps_link="new_gmap",  # Modified
        event_datetime=datetime(2024, 8, 10, 20, 0, tzinfo=UTC),  # Modified
        channel_id=1001,
        message_id=2001,
        open=True,
        archived=False,
        drinks=["Water"],  # Modified
        message=None,  # Assume message wasn't part of modification
    )


# --- Test Cases ---


# --- UPDATED PATCHES ---
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
    # --- END UPDATED PATCHES ---
    """Test the successful path of modify_offkai."""
    # Arrange
    event_name_to_modify = "Summer Bash"
    update_text = "Details updated!"
    new_venue = "New Venue"
    new_gmaps = "new_gmap"
    new_dt_str = "2024-08-10 20:00"
    new_drinks_str = "Water"

    mock_update_details.return_value = mock_modified_event
    # Mock the helper returning the thread
    mock_fetch_thread.return_value = mock_thread
    # Ensure thread ID matches event ID if needed
    mock_thread.id = mock_modified_event.channel_id
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
        drinks=new_drinks_str,
    )

    # Assert
    mock_update_details.assert_called_once_with(
        event_name=event_name_to_modify,
        venue=new_venue,
        address=None,
        google_maps_link=new_gmaps,
        date_time_str=new_dt_str,
        drinks_str=new_drinks_str,
    )
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once_with(ANY, mock_modified_event)  # ANY for client
    # Check fetching the thread via helper
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_modified_event)  # ANY for client
    # Check sending update message to thread
    mock_thread.send.assert_awaited_once_with(f"**Event Updated:**\n{update_text}")
    # Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )
    mock_log.warning.assert_not_called()


@pytest.mark.parametrize(
    "error_type, error_args",
    [
        (EventNotFoundError, ("NonExistent Event",)),
        (EventArchivedError, ("Archived Party", "modify")),
        (InvalidDateTimeFormatError, ()),
        (NoChangesProvidedError, ()),
    ],
)
# --- UPDATED PATCHES ---
@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main._log")
async def test_modify_offkai_data_layer_errors(
    mock_log,
    mock_update_details,
    mock_save_data,
    mock_update_msg_view,  # Renamed
    mock_fetch_thread,  # Renamed
    mock_interaction,
    error_type,
    error_args,
    prepopulated_event_cache,
):
    # --- END UPDATED PATCHES ---
    """Test handling of errors raised by update_event_details."""
    # Arrange
    event_name = error_args[0] if error_args else "Summer Bash"
    mock_update_details.side_effect = error_type(*error_args)

    # Act & Assert
    with pytest.raises(error_type):
        await main.modify_offkai.callback(
            mock_interaction,
            event_name=event_name,
            update_msg="Update attempt",
            venue="Attempt Venue",
        )

    mock_update_details.assert_called_once()
    mock_save_data.assert_not_called()
    mock_update_msg_view.assert_not_awaited()
    mock_fetch_thread.assert_not_awaited()  # Check helper wasn't called
    mock_interaction.response.send_message.assert_not_awaited()


# --- UPDATED TEST ---
@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main._log")
async def test_modify_offkai_fetch_thread_not_found_error(  # Renamed test
    mock_log,
    mock_update_details,
    mock_save_data,
    mock_update_msg_view,  # Renamed
    mock_fetch_thread,  # Renamed
    mock_interaction,
    mock_modified_event,
    prepopulated_event_cache,
):
    """Test modify_offkai when fetch_thread_for_event raises ThreadNotFoundError."""
    # Arrange
    event_name_to_modify = "Summer Bash"
    update_text = "Details updated!"
    mock_update_details.return_value = mock_modified_event
    # Mock the helper raising the error
    mock_fetch_thread.side_effect = ThreadNotFoundError(event_name_to_modify, mock_modified_event.channel_id)

    # Act
    await main.modify_offkai.callback(
        mock_interaction,
        event_name=event_name_to_modify,
        update_msg=update_text,
        venue="New Venue",
    )

    # Assert
    # Steps up to fetching thread should succeed
    mock_update_details.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_modified_event)

    # Sending update message should be skipped, warning logged
    mock_log.log.assert_called_once()
    assert mock_log.log.call_args[0][0] == logging.WARNING  # Default level for ThreadNotFoundError
    assert f"Could not send update message for event '{event_name_to_modify}'" in mock_log.log.call_args[0][1]
    assert "Could not find thread channel" in mock_log.log.call_args[0][1]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )


# --- END UPDATED TEST ---


# --- NEW TEST ---
@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main._log")
async def test_modify_offkai_fetch_thread_missing_id_error(
    mock_log,
    mock_update_details,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_interaction,
    mock_modified_event,
    prepopulated_event_cache,
):
    """Test modify_offkai when fetch_thread_for_event raises MissingChannelIDError."""
    # Arrange
    event_name_to_modify = "Summer Bash"
    update_text = "Details updated!"
    mock_update_details.return_value = mock_modified_event
    mock_fetch_thread.side_effect = MissingChannelIDError(event_name_to_modify)

    # Act
    await main.modify_offkai.callback(
        mock_interaction,
        event_name=event_name_to_modify,
        update_msg=update_text,
        venue="New Venue",
    )

    # Assert
    mock_update_details.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_modified_event)

    # Sending update message should be skipped, warning logged
    mock_log.log.assert_called_once()
    assert mock_log.log.call_args[0][0] == logging.WARNING  # Default level for MissingChannelIDError
    assert f"Could not send update message for event '{event_name_to_modify}'" in mock_log.log.call_args[0][1]
    assert "does not have a channel ID" in mock_log.log.call_args[0][1]

    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )


# --- END NEW TEST ---


# --- NEW TEST ---
@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main._log")
async def test_modify_offkai_fetch_thread_access_error(
    mock_log,
    mock_update_details,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_interaction,
    mock_modified_event,
    prepopulated_event_cache,
):
    """Test modify_offkai when fetch_thread_for_event raises ThreadAccessError."""
    # Arrange
    event_name_to_modify = "Summer Bash"
    update_text = "Details updated!"
    mock_update_details.return_value = mock_modified_event
    mock_fetch_thread.side_effect = ThreadAccessError(event_name_to_modify, mock_modified_event.channel_id)

    # Act
    await main.modify_offkai.callback(
        mock_interaction,
        event_name=event_name_to_modify,
        update_msg=update_text,
        venue="New Venue",
    )

    # Assert
    mock_update_details.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_modified_event)

    # Sending update message should be skipped, error logged
    mock_log.log.assert_called_once()
    assert mock_log.log.call_args[0][0] == logging.ERROR  # Check level for ThreadAccessError
    assert f"Could not send update message for event '{event_name_to_modify}'" in mock_log.log.call_args[0][1]
    assert "Bot lacks permissions" in mock_log.log.call_args[0][1]

    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )


# --- END NEW TEST ---


# --- UPDATED PATCHES ---
@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main._log")
async def test_modify_offkai_send_update_fails(
    mock_log,
    mock_update_details,
    mock_save_data,
    mock_update_msg_view,  # Renamed
    mock_fetch_thread,  # Renamed
    mock_interaction,
    mock_thread,  # Need the thread mock here
    mock_modified_event,
    prepopulated_event_cache,
):
    # --- END UPDATED PATCHES ---
    """Test modify_offkai when sending the update message fails."""
    # Arrange
    event_name_to_modify = "Summer Bash"
    update_text = "Details updated!"
    mock_update_details.return_value = mock_modified_event
    # Mock helper returning thread successfully
    mock_fetch_thread.return_value = mock_thread
    # Simulate error sending message
    send_error = discord.HTTPException(MagicMock(), "Cannot send messages")
    mock_thread.send.side_effect = send_error

    # Act
    await main.modify_offkai.callback(
        mock_interaction,
        event_name=event_name_to_modify,
        update_msg=update_text,
        venue="New Venue",
    )

    # Assert
    mock_update_details.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    # Assert helper was called
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
