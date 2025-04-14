# tests/commands/test_reopen_offkai.py

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands

# Import the function to test and relevant errors/classes
from offkai_bot import main
from offkai_bot.data.event import Event  # To create return value
from offkai_bot.errors import (
    EventAlreadyOpenError,
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
    interaction.command.name = "reopen_offkai"

    # Mock response methods
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    return interaction

@pytest.fixture
def mock_reopened_event(sample_event_list):
    """
    Fixture providing an Event object representing the state *after* reopening.
    Based on 'Autumn Meetup' from sample_event_list.
    """
    # Find the original 'Autumn Meetup' event (which is closed)
    original_event = next(e for e in sample_event_list if e.event_name == "Autumn Meetup")
    # Create a copy and modify the 'open' status
    reopened_event = Event(**original_event.__dict__) # Simple copy for dataclass
    reopened_event.open = True # Set to open
    return reopened_event

# --- Test Cases ---

@patch('offkai_bot.main.update_event_message', new_callable=AsyncMock)
@patch('offkai_bot.main.save_event_data')
@patch('offkai_bot.main.set_event_open_status')
@patch('offkai_bot.main.client') # Mock the client object to mock get_channel
@patch('offkai_bot.main._log')
async def test_reopen_offkai_success_with_message(
    mock_log,
    mock_client,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_thread, # From conftest.py
    mock_reopened_event, # From this file
    prepopulated_event_cache # Use fixture to ensure cache is populated
):
    """Test the successful path of reopen_offkai with a reopening message."""
    # Arrange
    event_name_to_reopen = "Autumn Meetup" # Use the event that starts closed
    reopen_text = "Responses are now open again!"

    # Mock the data layer function returning the reopened event
    mock_set_status.return_value = mock_reopened_event
    # Mock client.get_channel finding the thread (use the correct ID for Autumn Meetup)
    mock_reopened_event.channel_id = 1002 # Ensure fixture has correct ID
    mock_thread.id = 1002 # Adjust mock_thread ID for this test if needed
    mock_client.get_channel.return_value = mock_thread

    # Act
    await main.reopen_offkai.callback(
        mock_interaction,
        event_name=event_name_to_reopen,
        reopen_msg=reopen_text,
    )

    # Assert
    # 1. Check data layer call
    mock_set_status.assert_called_once_with(event_name_to_reopen, target_open_status=True)
    # 2. Check save call
    mock_save_data.assert_called_once()
    # 3. Check Discord message view update call
    mock_update_msg_view.assert_awaited_once_with(mock_client, mock_reopened_event)
    # 4. Check getting the channel
    mock_client.get_channel.assert_called_once_with(mock_reopened_event.channel_id)
    # 5. Check sending reopening message to thread
    mock_thread.send.assert_awaited_once_with(f"**Responses Reopened:**\n{reopen_text}")
    # 6. Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_reopen}' have been reopened."
    )
    # 7. Check logs (optional)
    mock_log.warning.assert_not_called()


@patch('offkai_bot.main.update_event_message', new_callable=AsyncMock)
@patch('offkai_bot.main.save_event_data')
@patch('offkai_bot.main.set_event_open_status')
@patch('offkai_bot.main.client')
@patch('offkai_bot.main._log')
async def test_reopen_offkai_success_no_message(
    mock_log,
    mock_client,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_thread, # Still need mock_thread for get_channel potentially
    mock_reopened_event,
    prepopulated_event_cache
):
    """Test the successful path of reopen_offkai without a reopening message."""
    # Arrange
    event_name_to_reopen = "Autumn Meetup"
    mock_set_status.return_value = mock_reopened_event
    mock_client.get_channel.return_value = mock_thread # Assume channel is found

    # Act
    await main.reopen_offkai.callback(
        mock_interaction,
        event_name=event_name_to_reopen,
        reopen_msg=None, # Explicitly None
    )

    # Assert
    # 1. Check data layer call
    mock_set_status.assert_called_once_with(event_name_to_reopen, target_open_status=True)
    # 2. Check save call
    mock_save_data.assert_called_once()
    # 3. Check Discord message view update call
    mock_update_msg_view.assert_awaited_once_with(mock_client, mock_reopened_event)
    # 4. Check getting the channel was NOT called (because reopen_msg is None)
    mock_client.get_channel.assert_not_called()
    # 5. Check sending reopening message was NOT called
    mock_thread.send.assert_not_awaited()
    # 6. Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_reopen}' have been reopened."
    )
    # 7. Check logs
    mock_log.warning.assert_not_called()


@pytest.mark.parametrize(
    "error_type, error_args",
    [
        (EventNotFoundError, ("NonExistent Event",)),
        (EventArchivedError, ("Archived Party", "open")),
        (EventAlreadyOpenError, ("Summer Bash",)), # Use an already open event
    ]
)
@patch('offkai_bot.main.update_event_message', new_callable=AsyncMock)
@patch('offkai_bot.main.save_event_data')
@patch('offkai_bot.main.set_event_open_status')
@patch('offkai_bot.main.client')
@patch('offkai_bot.main._log')
async def test_reopen_offkai_data_layer_errors(
    mock_log,
    mock_client,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    error_type,
    error_args,
    prepopulated_event_cache
):
    """Test handling of errors raised by set_event_open_status when reopening."""
    # Arrange
    event_name = error_args[0] # Get relevant event name from args
    mock_set_status.side_effect = error_type(*error_args)

    # Act & Assert
    with pytest.raises(error_type):
        await main.reopen_offkai.callback(
            mock_interaction,
            event_name=event_name,
            reopen_msg="Attempting to reopen",
        )

    # Assert data layer call was made
    mock_set_status.assert_called_once()
    # Assert subsequent steps were NOT called
    mock_save_data.assert_not_called()
    mock_update_msg_view.assert_not_awaited()
    mock_client.get_channel.assert_not_called()
    mock_interaction.response.send_message.assert_not_awaited() # Error handler deals with response


@patch('offkai_bot.main.update_event_message', new_callable=AsyncMock)
@patch('offkai_bot.main.save_event_data')
@patch('offkai_bot.main.set_event_open_status')
@patch('offkai_bot.main.client')
@patch('offkai_bot.main._log')
async def test_reopen_offkai_thread_not_found(
    mock_log,
    mock_client,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_reopened_event,
    prepopulated_event_cache
):
    """Test reopen_offkai when the thread channel is not found."""
    # Arrange
    event_name_to_reopen = "Autumn Meetup"
    reopen_text = "Reopening!"
    mock_set_status.return_value = mock_reopened_event
    mock_client.get_channel.return_value = None # Simulate thread not found

    # Act
    await main.reopen_offkai.callback(
        mock_interaction,
        event_name=event_name_to_reopen,
        reopen_msg=reopen_text,
    )

    # Assert
    # Steps up to finding channel should succeed
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_client.get_channel.assert_called_once_with(mock_reopened_event.channel_id)

    # Sending update message should be skipped, warning logged
    mock_log.warning.assert_called_once()
    assert f"Could not find thread {mock_reopened_event.channel_id}" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_reopen}' have been reopened."
    )


@patch('offkai_bot.main.update_event_message', new_callable=AsyncMock)
@patch('offkai_bot.main.save_event_data')
@patch('offkai_bot.main.set_event_open_status')
@patch('offkai_bot.main.client')
@patch('offkai_bot.main._log')
async def test_reopen_offkai_send_reopen_msg_fails(
    mock_log,
    mock_client,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_thread, # Need the thread mock here
    mock_reopened_event,
    prepopulated_event_cache
):
    """Test reopen_offkai when sending the reopening message fails."""
    # Arrange
    event_name_to_reopen = "Autumn Meetup"
    reopen_text = "Reopening!"
    mock_set_status.return_value = mock_reopened_event
    mock_client.get_channel.return_value = mock_thread
    # Simulate error sending message
    send_error = discord.HTTPException(MagicMock(), "Cannot send messages")
    mock_thread.send.side_effect = send_error

    # Act
    await main.reopen_offkai.callback(
        mock_interaction,
        event_name=event_name_to_reopen,
        reopen_msg=reopen_text,
    )

    # Assert
    # Steps up to sending message should succeed
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_client.get_channel.assert_called_once_with(mock_reopened_event.channel_id)
    mock_thread.send.assert_awaited_once_with(f"**Responses Reopened:**\n{reopen_text}")

    # Warning should be logged for send failure
    mock_log.warning.assert_called_once()
    assert f"Could not send reopening message to thread {mock_thread.id}" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_reopen}' have been reopened."
    )


@patch('offkai_bot.main.update_event_message', new_callable=AsyncMock)
@patch('offkai_bot.main.save_event_data')
@patch('offkai_bot.main.set_event_open_status')
@patch('offkai_bot.main.client')
@patch('offkai_bot.main._log')
async def test_reopen_offkai_missing_channel_id(
    mock_log,
    mock_client,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_reopened_event,
    prepopulated_event_cache
):
    """Test reopen_offkai when the event object is missing a channel_id."""
    # Arrange
    event_name_to_reopen = "Autumn Meetup"
    reopen_text = "Reopening!"
    # Modify the event fixture to lack channel_id for this test
    mock_reopened_event.channel_id = None
    mock_set_status.return_value = mock_reopened_event

    # Act
    await main.reopen_offkai.callback(
        mock_interaction,
        event_name=event_name_to_reopen,
        reopen_msg=reopen_text,
    )

    # Assert
    # Steps up to Discord interactions should succeed
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()

    # Getting channel and sending update should be skipped, warning logged
    mock_client.get_channel.assert_not_called()
    mock_log.warning.assert_called_once()
    assert f"Event '{event_name_to_reopen}' is missing channel_id" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_reopen}' have been reopened."
    )
