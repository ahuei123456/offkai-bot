# tests/commands/test_modify_offkai.py

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

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
    NoChangesProvidedError,
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


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main.client")  # Mock the client object to mock get_channel
@patch("offkai_bot.main._log")
async def test_modify_offkai_success(
    mock_log,
    mock_client,
    mock_update_details,
    mock_save_data,
    mock_update_msg,
    mock_interaction,
    mock_thread,
    mock_modified_event,
    prepopulated_event_cache,  # Use fixture to ensure cache is populated
):
    """Test the successful path of modify_offkai."""
    # Arrange
    event_name_to_modify = "Summer Bash"
    update_text = "Details updated!"
    new_venue = "New Venue"
    new_gmaps = "new_gmap"
    new_dt_str = "2024-08-10 20:00"
    new_drinks_str = "Water"

    # Mock the data layer function returning the modified event
    mock_update_details.return_value = mock_modified_event
    # Mock client.get_channel finding the thread
    mock_client.get_channel.return_value = mock_thread

    # Act
    await main.modify_offkai.callback(
        mock_interaction,
        event_name=event_name_to_modify,
        update_msg=update_text,
        venue=new_venue,
        address=None,  # Not changing address
        google_maps_link=new_gmaps,
        date_time=new_dt_str,
        drinks=new_drinks_str,
    )

    # Assert
    # 1. Check data layer call
    mock_update_details.assert_called_once_with(
        event_name=event_name_to_modify,
        venue=new_venue,
        address=None,
        google_maps_link=new_gmaps,
        date_time_str=new_dt_str,
        drinks_str=new_drinks_str,
    )
    # 2. Check save call
    mock_save_data.assert_called_once()
    # 3. Check Discord message update call
    mock_update_msg.assert_awaited_once_with(mock_client, mock_modified_event)
    # 4. Check getting the channel
    mock_client.get_channel.assert_called_once_with(mock_modified_event.channel_id)
    # 5. Check sending update message to thread
    mock_thread.send.assert_awaited_once_with(f"**Event Updated:**\n{update_text}")
    # 6. Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )
    # 7. Check logs (optional)
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
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_modify_offkai_data_layer_errors(
    mock_log,
    mock_client,
    mock_update_details,
    mock_save_data,
    mock_update_msg,
    mock_interaction,
    error_type,
    error_args,
    prepopulated_event_cache,
):
    """Test handling of errors raised by update_event_details."""
    # Arrange
    event_name = error_args[0] if error_args else "Summer Bash"  # Use relevant event name
    mock_update_details.side_effect = error_type(*error_args)

    # Act & Assert
    with pytest.raises(error_type):
        await main.modify_offkai.callback(
            mock_interaction,
            event_name=event_name,
            update_msg="Update attempt",
            venue="Attempt Venue",  # Provide some args
        )

    # Assert data layer call was made
    mock_update_details.assert_called_once()
    # Assert subsequent steps were NOT called
    mock_save_data.assert_not_called()
    mock_update_msg.assert_not_awaited()
    mock_client.get_channel.assert_not_called()
    mock_interaction.response.send_message.assert_not_awaited()  # Error handler deals with response


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_modify_offkai_thread_not_found(
    mock_log,
    mock_client,
    mock_update_details,
    mock_save_data,
    mock_update_msg,
    mock_interaction,
    mock_modified_event,  # Use the modified event state
    prepopulated_event_cache,
):
    """Test modify_offkai when the thread channel is not found."""
    # Arrange
    event_name_to_modify = "Summer Bash"
    update_text = "Details updated!"
    mock_update_details.return_value = mock_modified_event
    mock_client.get_channel.return_value = None  # Simulate thread not found

    # Act
    await main.modify_offkai.callback(
        mock_interaction,
        event_name=event_name_to_modify,
        update_msg=update_text,
        venue="New Venue",  # Need some modification args
    )

    # Assert
    # Steps up to finding channel should succeed
    mock_update_details.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg.assert_awaited_once()
    mock_client.get_channel.assert_called_once_with(mock_modified_event.channel_id)

    # Sending update message should be skipped, warning logged
    # mock_thread.send is not available as get_channel returned None
    mock_log.warning.assert_called_once()
    assert f"Could not find thread {mock_modified_event.channel_id}" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_modify_offkai_send_update_fails(
    mock_log,
    mock_client,
    mock_update_details,
    mock_save_data,
    mock_update_msg,
    mock_interaction,
    mock_thread,  # Need the thread mock here
    mock_modified_event,
    prepopulated_event_cache,
):
    """Test modify_offkai when sending the update message fails."""
    # Arrange
    event_name_to_modify = "Summer Bash"
    update_text = "Details updated!"
    mock_update_details.return_value = mock_modified_event
    mock_client.get_channel.return_value = mock_thread
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
    # Steps up to sending message should succeed
    mock_update_details.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg.assert_awaited_once()
    mock_client.get_channel.assert_called_once_with(mock_modified_event.channel_id)
    mock_thread.send.assert_awaited_once_with(f"**Event Updated:**\n{update_text}")

    # Warning should be logged for send failure
    mock_log.warning.assert_called_once()
    assert f"Could not send update message to thread {mock_thread.id}" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.update_event_details")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_modify_offkai_missing_channel_id(
    mock_log,
    mock_client,
    mock_update_details,
    mock_save_data,
    mock_update_msg,
    mock_interaction,
    mock_modified_event,  # Use the modified event state
    prepopulated_event_cache,
):
    """Test modify_offkai when the event object is missing a channel_id."""
    # Arrange
    event_name_to_modify = "Summer Bash"
    update_text = "Details updated!"
    # Modify the event fixture to lack channel_id for this test
    mock_modified_event.channel_id = None
    mock_update_details.return_value = mock_modified_event

    # Act
    await main.modify_offkai.callback(
        mock_interaction,
        event_name=event_name_to_modify,
        update_msg=update_text,
        venue="New Venue",
    )

    # Assert
    # Steps up to Discord interactions should succeed
    mock_update_details.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg.assert_awaited_once()

    # Getting channel and sending update should be skipped, warning logged
    mock_client.get_channel.assert_not_called()
    mock_log.warning.assert_called_once()
    assert f"Event '{event_name_to_modify}' is missing channel_id" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_modify}' modified successfully. Announcement posted in thread (if possible)."
    )
