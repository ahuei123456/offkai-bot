# tests/commands/test_broadcast.py

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands

# Import the function to test and relevant errors/classes
from offkai_bot import main
from offkai_bot.errors import (
    BroadcastPermissionError,
    BroadcastSendError,
    EventNotFoundError,
    MissingChannelIDError,
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
    interaction.command.name = "broadcast"

    # Mock response methods
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock(send=AsyncMock())  # In case response is done

    return interaction

# --- Test Cases ---

@patch('offkai_bot.main.get_event')
@patch('offkai_bot.main.client') # Mock the client object to mock get_channel
@patch('offkai_bot.main._log')
async def test_broadcast_success(
    mock_log,
    mock_client,
    mock_get_event,
    mock_interaction,
    mock_thread, # From conftest.py
    prepopulated_event_cache # Use fixture to ensure cache is populated
):
    """Test the successful path of broadcast."""
    # Arrange
    event_name_to_broadcast = "Summer Bash"
    broadcast_message = "Important update!"
    # Find the event from the prepopulated cache to get expected channel_id
    target_event = next(e for e in prepopulated_event_cache if e.event_name == event_name_to_broadcast)

    mock_get_event.return_value = target_event
    mock_client.get_channel.return_value = mock_thread
    # Ensure mock_thread ID matches target_event.channel_id if necessary
    mock_thread.id = target_event.channel_id
    mock_thread.mention = f"<#{mock_thread.id}>"


    # Act
    await main.broadcast.callback(
        mock_interaction,
        event_name=event_name_to_broadcast,
        message=broadcast_message,
    )

    # Assert
    # 1. Check data layer call
    mock_get_event.assert_called_once_with(event_name_to_broadcast)
    # 2. Check getting the channel
    mock_client.get_channel.assert_called_once_with(target_event.channel_id)
    # 3. Check sending message to thread
    mock_thread.send.assert_awaited_once_with(f"{broadcast_message}")
    # 4. Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"📣 Sent broadcast to channel {mock_thread.mention}.", ephemeral=True
    )
    # 5. Check logs (optional)
    mock_log.warning.assert_not_called()
    mock_log.error.assert_not_called()


@patch('offkai_bot.main.get_event')
@patch('offkai_bot.main.client')
@patch('offkai_bot.main._log')
async def test_broadcast_event_not_found(
    mock_log,
    mock_client,
    mock_get_event,
    mock_interaction,
    prepopulated_event_cache # Still useful to ensure cache is cleared etc.
):
    """Test broadcast when the event is not found."""
    # Arrange
    event_name = "NonExistent Event"
    broadcast_message = "Test message"
    mock_get_event.side_effect = EventNotFoundError(event_name)

    # Act & Assert
    with pytest.raises(EventNotFoundError):
        await main.broadcast.callback(
            mock_interaction,
            event_name=event_name,
            message=broadcast_message,
        )

    # Assert get_event was called
    mock_get_event.assert_called_once_with(event_name)
    # Assert subsequent steps were NOT called
    mock_client.get_channel.assert_not_called()
    mock_interaction.response.send_message.assert_not_awaited()


@patch('offkai_bot.main.get_event')
@patch('offkai_bot.main.client')
@patch('offkai_bot.main._log')
async def test_broadcast_missing_channel_id(
    mock_log,
    mock_client,
    mock_get_event,
    mock_interaction,
    prepopulated_event_cache
):
    """Test broadcast when the found event has no channel_id."""
    # Arrange
    event_name = "Summer Bash"
    broadcast_message = "Test message"
    # Get event and modify it
    target_event = next(e for e in prepopulated_event_cache if e.event_name == event_name)
    target_event.channel_id = None # Remove channel_id
    mock_get_event.return_value = target_event

    # Act & Assert
    with pytest.raises(MissingChannelIDError) as exc_info:
        await main.broadcast.callback(
            mock_interaction,
            event_name=event_name,
            message=broadcast_message,
        )

    assert exc_info.value.event_name == event_name
    mock_get_event.assert_called_once_with(event_name)
    # Assert subsequent steps were NOT called
    mock_client.get_channel.assert_not_called()
    mock_interaction.response.send_message.assert_not_awaited()


@patch('offkai_bot.main.get_event')
@patch('offkai_bot.main.client')
@patch('offkai_bot.main._log')
async def test_broadcast_thread_not_found(
    mock_log,
    mock_client,
    mock_get_event,
    mock_interaction,
    prepopulated_event_cache
):
    """Test broadcast when client.get_channel returns None."""
    # Arrange
    event_name = "Summer Bash"
    broadcast_message = "Test message"
    target_event = next(e for e in prepopulated_event_cache if e.event_name == event_name)
    mock_get_event.return_value = target_event
    mock_client.get_channel.return_value = None # Simulate thread not found

    # Act & Assert
    with pytest.raises(ThreadNotFoundError) as exc_info:
        await main.broadcast.callback(
            mock_interaction,
            event_name=event_name,
            message=broadcast_message,
        )

    assert exc_info.value.event_name == event_name
    assert exc_info.value.channel_id == target_event.channel_id
    mock_get_event.assert_called_once_with(event_name)
    mock_client.get_channel.assert_called_once_with(target_event.channel_id)
    # Assert subsequent steps were NOT called
    mock_interaction.response.send_message.assert_not_awaited()


@patch('offkai_bot.main.get_event')
@patch('offkai_bot.main.client')
@patch('offkai_bot.main._log')
async def test_broadcast_channel_not_thread(
    mock_log,
    mock_client,
    mock_get_event,
    mock_interaction,
    prepopulated_event_cache
):
    """Test broadcast when client.get_channel returns a non-Thread channel."""
    # Arrange
    event_name = "Summer Bash"
    broadcast_message = "Test message"
    target_event = next(e for e in prepopulated_event_cache if e.event_name == event_name)
    mock_get_event.return_value = target_event
    # Simulate returning a TextChannel instead of a Thread
    mock_text_channel = MagicMock(spec=discord.TextChannel)
    mock_client.get_channel.return_value = mock_text_channel

    # Act & Assert
    with pytest.raises(ThreadNotFoundError) as exc_info: # Still raises ThreadNotFound based on isinstance check
        await main.broadcast.callback(
            mock_interaction,
            event_name=event_name,
            message=broadcast_message,
        )

    assert exc_info.value.event_name == event_name
    assert exc_info.value.channel_id == target_event.channel_id
    mock_get_event.assert_called_once_with(event_name)
    mock_client.get_channel.assert_called_once_with(target_event.channel_id)
    # Assert subsequent steps were NOT called
    mock_interaction.response.send_message.assert_not_awaited()


@patch('offkai_bot.main.get_event')
@patch('offkai_bot.main.client')
@patch('offkai_bot.main._log')
async def test_broadcast_send_permission_error(
    mock_log,
    mock_client,
    mock_get_event,
    mock_interaction,
    mock_thread, # Need thread mock
    prepopulated_event_cache
):
    """Test broadcast when thread.send raises discord.Forbidden."""
    # Arrange
    event_name = "Summer Bash"
    broadcast_message = "Test message"
    target_event = next(e for e in prepopulated_event_cache if e.event_name == event_name)
    mock_get_event.return_value = target_event
    mock_client.get_channel.return_value = mock_thread
    # Simulate permission error
    forbidden_error = discord.Forbidden(MagicMock(), "Missing Permissions")
    mock_thread.send.side_effect = forbidden_error

    # Act & Assert
    with pytest.raises(BroadcastPermissionError) as exc_info:
        await main.broadcast.callback(
            mock_interaction,
            event_name=event_name,
            message=broadcast_message,
        )

    assert exc_info.value.channel is mock_thread
    assert exc_info.value.original_exception is forbidden_error
    mock_get_event.assert_called_once_with(event_name)
    mock_client.get_channel.assert_called_once_with(target_event.channel_id)
    mock_thread.send.assert_awaited_once_with(f"{broadcast_message}")
    # Assert final response was NOT called
    mock_interaction.response.send_message.assert_not_awaited()


@patch('offkai_bot.main.get_event')
@patch('offkai_bot.main.client')
@patch('offkai_bot.main._log')
async def test_broadcast_send_http_error(
    mock_log,
    mock_client,
    mock_get_event,
    mock_interaction,
    mock_thread, # Need thread mock
    prepopulated_event_cache
):
    """Test broadcast when thread.send raises discord.HTTPException."""
    # Arrange
    event_name = "Summer Bash"
    broadcast_message = "Test message"
    target_event = next(e for e in prepopulated_event_cache if e.event_name == event_name)
    mock_get_event.return_value = target_event
    mock_client.get_channel.return_value = mock_thread
    # Simulate generic HTTP error
    http_error = discord.HTTPException(MagicMock(), "Network Error")
    mock_thread.send.side_effect = http_error

    # Act & Assert
    with pytest.raises(BroadcastSendError) as exc_info:
        await main.broadcast.callback(
            mock_interaction,
            event_name=event_name,
            message=broadcast_message,
        )

    assert exc_info.value.channel is mock_thread
    assert exc_info.value.original_exception is http_error
    mock_get_event.assert_called_once_with(event_name)
    mock_client.get_channel.assert_called_once_with(target_event.channel_id)
    mock_thread.send.assert_awaited_once_with(f"{broadcast_message}")
    # Assert final response was NOT called
    mock_interaction.response.send_message.assert_not_awaited()

