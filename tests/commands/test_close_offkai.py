# tests/commands/test_close_offkai.py

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands

# Import the function to test and relevant errors/classes
from offkai_bot import main
from offkai_bot.data.event import Event  # To create return value
from offkai_bot.errors import (
    EventAlreadyClosedError,  # Import base class for broader catches if needed
    EventArchivedError,
    EventNotFoundError,
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
    interaction.command.name = "close_offkai"

    # Mock response methods
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    return interaction


@pytest.fixture
def mock_closed_event(sample_event_list):
    """
    Fixture providing an Event object representing the state *after* closing.
    Based on 'Summer Bash' from sample_event_list.
    """
    # Find the original 'Summer Bash' event
    original_event = next(e for e in sample_event_list if e.event_name == "Summer Bash")
    # Create a copy and modify the 'open' status
    closed_event = Event(**original_event.__dict__)  # Simple copy for dataclass
    closed_event.open = False
    return closed_event


# --- Test Cases ---


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.set_event_open_status")
@patch("offkai_bot.main.client")  # Mock the client object to mock get_channel
@patch("offkai_bot.main._log")
async def test_close_offkai_success_with_message(
    mock_log,
    mock_client,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_thread,  # From conftest.py
    mock_closed_event,  # From this file
    prepopulated_event_cache,  # Use fixture to ensure cache is populated
):
    """Test the successful path of close_offkai with a closing message."""
    # Arrange
    event_name_to_close = "Summer Bash"
    close_text = "Responses are now closed!"

    # Mock the data layer function returning the closed event
    mock_set_status.return_value = mock_closed_event
    # Mock client.get_channel finding the thread
    mock_client.get_channel.return_value = mock_thread

    # Act
    await main.close_offkai.callback(
        mock_interaction,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    # 1. Check data layer call
    mock_set_status.assert_called_once_with(event_name_to_close, target_open_status=False)
    # 2. Check save call
    mock_save_data.assert_called_once()
    # 3. Check Discord message view update call
    mock_update_msg_view.assert_awaited_once_with(mock_client, mock_closed_event)
    # 4. Check getting the channel
    mock_client.get_channel.assert_called_once_with(mock_closed_event.channel_id)
    # 5. Check sending closing message to thread
    mock_thread.send.assert_awaited_once_with(f"**Responses Closed:**\n{close_text}")
    # 6. Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_close}' have been closed."
    )
    # 7. Check logs (optional)
    mock_log.warning.assert_not_called()


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.set_event_open_status")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_close_offkai_success_no_message(
    mock_log,
    mock_client,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_thread,  # Still need mock_thread for get_channel potentially
    mock_closed_event,
    prepopulated_event_cache,
):
    """Test the successful path of close_offkai without a closing message."""
    # Arrange
    event_name_to_close = "Summer Bash"
    mock_set_status.return_value = mock_closed_event
    mock_client.get_channel.return_value = mock_thread  # Assume channel is found

    # Act
    await main.close_offkai.callback(
        mock_interaction,
        event_name=event_name_to_close,
        close_msg=None,  # Explicitly None
    )

    # Assert
    # 1. Check data layer call
    mock_set_status.assert_called_once_with(event_name_to_close, target_open_status=False)
    # 2. Check save call
    mock_save_data.assert_called_once()
    # 3. Check Discord message view update call
    mock_update_msg_view.assert_awaited_once_with(mock_client, mock_closed_event)
    # 4. Check getting the channel was NOT called (because close_msg is None)
    mock_client.get_channel.assert_not_called()
    # 5. Check sending closing message was NOT called
    mock_thread.send.assert_not_awaited()
    # 6. Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_close}' have been closed."
    )
    # 7. Check logs
    mock_log.warning.assert_not_called()


@pytest.mark.parametrize(
    "error_type, error_args",
    [
        (EventNotFoundError, ("NonExistent Event",)),
        (EventArchivedError, ("Archived Party", "close")),
        (EventAlreadyClosedError, ("Autumn Meetup",)),  # Use an already closed event
    ],
)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.set_event_open_status")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_close_offkai_data_layer_errors(
    mock_log,
    mock_client,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    error_type,
    error_args,
    prepopulated_event_cache,
):
    """Test handling of errors raised by set_event_open_status."""
    # Arrange
    event_name = error_args[0]  # Get relevant event name from args
    mock_set_status.side_effect = error_type(*error_args)

    # Act & Assert
    with pytest.raises(error_type):
        await main.close_offkai.callback(
            mock_interaction,
            event_name=event_name,
            close_msg="Attempting to close",
        )

    # Assert data layer call was made
    mock_set_status.assert_called_once()
    # Assert subsequent steps were NOT called
    mock_save_data.assert_not_called()
    mock_update_msg_view.assert_not_awaited()
    mock_client.get_channel.assert_not_called()
    mock_interaction.response.send_message.assert_not_awaited()  # Error handler deals with response


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.set_event_open_status")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_close_offkai_thread_not_found(
    mock_log,
    mock_client,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_closed_event,
    prepopulated_event_cache,
):
    """Test close_offkai when the thread channel is not found."""
    # Arrange
    event_name_to_close = "Summer Bash"
    close_text = "Closing!"
    mock_set_status.return_value = mock_closed_event
    mock_client.get_channel.return_value = None  # Simulate thread not found

    # Act
    await main.close_offkai.callback(
        mock_interaction,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    # Steps up to finding channel should succeed
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_client.get_channel.assert_called_once_with(mock_closed_event.channel_id)

    # Sending update message should be skipped, warning logged
    mock_log.warning.assert_called_once()
    assert f"Could not find thread {mock_closed_event.channel_id}" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_close}' have been closed."
    )


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.set_event_open_status")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_close_offkai_send_close_msg_fails(
    mock_log,
    mock_client,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_thread,  # Need the thread mock here
    mock_closed_event,
    prepopulated_event_cache,
):
    """Test close_offkai when sending the closing message fails."""
    # Arrange
    event_name_to_close = "Summer Bash"
    close_text = "Closing!"
    mock_set_status.return_value = mock_closed_event
    mock_client.get_channel.return_value = mock_thread
    # Simulate error sending message
    send_error = discord.HTTPException(MagicMock(), "Cannot send messages")
    mock_thread.send.side_effect = send_error

    # Act
    await main.close_offkai.callback(
        mock_interaction,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    # Steps up to sending message should succeed
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_client.get_channel.assert_called_once_with(mock_closed_event.channel_id)
    mock_thread.send.assert_awaited_once_with(f"**Responses Closed:**\n{close_text}")

    # Warning should be logged for send failure
    mock_log.warning.assert_called_once()
    assert f"Could not send closing message to thread {mock_thread.id}" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_close}' have been closed."
    )


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.set_event_open_status")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_close_offkai_missing_channel_id(
    mock_log,
    mock_client,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_closed_event,
    prepopulated_event_cache,
):
    """Test close_offkai when the event object is missing a channel_id."""
    # Arrange
    event_name_to_close = "Summer Bash"
    close_text = "Closing!"
    # Modify the event fixture to lack channel_id for this test
    mock_closed_event.channel_id = None
    mock_set_status.return_value = mock_closed_event

    # Act
    await main.close_offkai.callback(
        mock_interaction,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    # Steps up to Discord interactions should succeed
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()

    # Getting channel and sending update should be skipped, warning logged
    mock_client.get_channel.assert_not_called()
    mock_log.warning.assert_called_once()
    assert f"Event '{event_name_to_close}' is missing channel_id" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_close}' have been closed."
    )
