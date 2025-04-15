# tests/commands/test_broadcast.py

from unittest.mock import ANY, AsyncMock, MagicMock, patch

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
    interaction.command.name = "broadcast"

    # Mock response methods
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock(send=AsyncMock())  # In case response is done

    return interaction


# --- Test Cases ---


@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_broadcast_success(
    mock_log,
    mock_get_event,
    mock_fetch_thread,  # Renamed from mock_client
    mock_interaction,
    mock_thread,  # From conftest.py
    prepopulated_event_cache,  # Use fixture to ensure cache is populated
):
    """Test the successful path of broadcast."""
    # Arrange
    event_name_to_broadcast = "Summer Bash"
    broadcast_message = "Important update!"
    target_event = next(e for e in prepopulated_event_cache if e.event_name == event_name_to_broadcast)

    mock_get_event.return_value = target_event
    # Mock the helper function returning the thread
    mock_fetch_thread.return_value = mock_thread
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
    # 2. Check fetching the thread via helper
    mock_fetch_thread.assert_awaited_once_with(ANY, target_event)  # ANY for client
    # 3. Check sending message to thread
    mock_thread.send.assert_awaited_once_with(f"{broadcast_message}")
    # 4. Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"📣 Sent broadcast to channel {mock_thread.mention}.", ephemeral=True
    )
    # 5. Check logs (optional)
    mock_log.warning.assert_not_called()
    mock_log.error.assert_not_called()


@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_broadcast_event_not_found(
    mock_log,
    mock_get_event,
    mock_fetch_thread,  # Added mock
    mock_interaction,
    prepopulated_event_cache,
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
    mock_fetch_thread.assert_not_awaited()  # Check helper wasn't called
    mock_interaction.response.send_message.assert_not_awaited()


@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_broadcast_missing_channel_id(
    mock_log,
    mock_get_event,
    mock_fetch_thread,  # Added mock
    mock_interaction,
    prepopulated_event_cache,
):
    """Test broadcast when fetch_thread_for_event raises MissingChannelIDError."""
    # Arrange
    event_name = "Summer Bash"
    broadcast_message = "Test message"
    target_event = next(e for e in prepopulated_event_cache if e.event_name == event_name)
    # Don't need to modify target_event anymore, just mock the helper's behavior
    mock_get_event.return_value = target_event
    # Mock the helper raising the error
    mock_fetch_thread.side_effect = MissingChannelIDError(event_name)

    # Act & Assert
    with pytest.raises(MissingChannelIDError) as exc_info:
        await main.broadcast.callback(
            mock_interaction,
            event_name=event_name,
            message=broadcast_message,
        )

    assert exc_info.value.event_name == event_name
    mock_get_event.assert_called_once_with(event_name)
    # Assert helper was called
    mock_fetch_thread.assert_awaited_once_with(ANY, target_event)
    # Assert subsequent steps were NOT called
    mock_interaction.response.send_message.assert_not_awaited()


@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_broadcast_thread_not_found_error(  # Renamed test slightly
    mock_log,
    mock_get_event,
    mock_fetch_thread,  # Added mock
    mock_interaction,
    prepopulated_event_cache,
):
    """Test broadcast when fetch_thread_for_event raises ThreadNotFoundError."""
    # Arrange
    event_name = "Summer Bash"
    broadcast_message = "Test message"
    target_event = next(e for e in prepopulated_event_cache if e.event_name == event_name)
    mock_get_event.return_value = target_event
    # Mock the helper raising the error
    mock_fetch_thread.side_effect = ThreadNotFoundError(event_name, target_event.channel_id)

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
    # Assert helper was called
    mock_fetch_thread.assert_awaited_once_with(ANY, target_event)
    # Assert subsequent steps were NOT called
    mock_interaction.response.send_message.assert_not_awaited()


@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_broadcast_thread_access_error(  # New test for access error
    mock_log,
    mock_get_event,
    mock_fetch_thread,  # Added mock
    mock_interaction,
    prepopulated_event_cache,
):
    """Test broadcast when fetch_thread_for_event raises ThreadAccessError."""
    # Arrange
    event_name = "Summer Bash"
    broadcast_message = "Test message"
    target_event = next(e for e in prepopulated_event_cache if e.event_name == event_name)
    mock_get_event.return_value = target_event
    # Mock the helper raising the error
    original_discord_error = discord.Forbidden(MagicMock(), "Cannot fetch")
    mock_fetch_thread.side_effect = ThreadAccessError(event_name, target_event.channel_id, original_discord_error)

    # Act & Assert
    with pytest.raises(ThreadAccessError) as exc_info:
        await main.broadcast.callback(
            mock_interaction,
            event_name=event_name,
            message=broadcast_message,
        )

    assert exc_info.value.event_name == event_name
    assert exc_info.value.channel_id == target_event.channel_id
    assert exc_info.value.original_exception is original_discord_error
    mock_get_event.assert_called_once_with(event_name)
    # Assert helper was called
    mock_fetch_thread.assert_awaited_once_with(ANY, target_event)
    # Assert subsequent steps were NOT called
    mock_interaction.response.send_message.assert_not_awaited()


@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_broadcast_send_permission_error(
    mock_log,
    mock_get_event,
    mock_fetch_thread,  # Added mock
    mock_interaction,
    mock_thread,  # Need thread mock
    prepopulated_event_cache,
):
    """Test broadcast when thread.send raises discord.Forbidden."""
    # Arrange
    event_name = "Summer Bash"
    broadcast_message = "Test message"
    target_event = next(e for e in prepopulated_event_cache if e.event_name == event_name)
    mock_get_event.return_value = target_event
    # Mock helper returning the thread successfully
    mock_fetch_thread.return_value = mock_thread
    # Simulate permission error on send
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
    # Assert helper was called
    mock_fetch_thread.assert_awaited_once_with(ANY, target_event)
    # Assert send was called
    mock_thread.send.assert_awaited_once_with(f"{broadcast_message}")
    # Assert final response was NOT called
    mock_interaction.response.send_message.assert_not_awaited()


@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main._log")
async def test_broadcast_send_http_error(
    mock_log,
    mock_get_event,
    mock_fetch_thread,  # Added mock
    mock_interaction,
    mock_thread,  # Need thread mock
    prepopulated_event_cache,
):
    """Test broadcast when thread.send raises discord.HTTPException."""
    # Arrange
    event_name = "Summer Bash"
    broadcast_message = "Test message"
    target_event = next(e for e in prepopulated_event_cache if e.event_name == event_name)
    mock_get_event.return_value = target_event
    # Mock helper returning the thread successfully
    mock_fetch_thread.return_value = mock_thread
    # Simulate generic HTTP error on send
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
    # Assert helper was called
    mock_fetch_thread.assert_awaited_once_with(ANY, target_event)
    # Assert send was called
    mock_thread.send.assert_awaited_once_with(f"{broadcast_message}")
    # Assert final response was NOT called
    mock_interaction.response.send_message.assert_not_awaited()
