# tests/alerts/test_task.py

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

# Import classes to test
from offkai_bot.alerts.task import CloseOffkaiTask, SendMessageTask

# Import errors for simulation/checking
from offkai_bot.errors import EventNotFoundError

# pytest marker for async tests
pytestmark = pytest.mark.asyncio

# --- Fixtures ---


@pytest.fixture
def mock_client():
    """Fixture for a mock discord.Client."""
    client = MagicMock(spec=discord.Client)
    client.get_channel = MagicMock()  # Mock the get_channel method
    return client


@pytest.fixture
def mock_text_channel():
    """Fixture for a mock discord.TextChannel."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 12345
    channel.send = AsyncMock()
    return channel


@pytest.fixture
def mock_thread():
    """Fixture for a mock discord.Thread."""
    thread = MagicMock(spec=discord.Thread)
    thread.id = 67890
    thread.send = AsyncMock()
    return thread


@pytest.fixture
def mock_other_channel():
    """Fixture for a mock channel that is not TextChannel or Thread."""
    channel = MagicMock(spec=discord.VoiceChannel)  # Example: VoiceChannel
    channel.id = 99999
    return channel


# --- Tests for SendMessageTask ---


@patch("offkai_bot.alerts.task._log")
async def test_send_message_task_success_text_channel(mock_log, mock_client, mock_text_channel):
    """Test SendMessageTask successfully sends to a TextChannel."""
    # Arrange
    channel_id = mock_text_channel.id
    message_content = "Hello Channel!"
    task = SendMessageTask(client=mock_client, channel_id=channel_id, message=message_content)
    mock_client.get_channel.return_value = mock_text_channel

    # Act
    await task.action()

    # Assert
    mock_client.get_channel.assert_called_once_with(channel_id)
    mock_text_channel.send.assert_awaited_once_with(message_content)
    mock_log.debug.assert_called_once_with(f"Executing SendMessageTask for channel {channel_id}")
    mock_log.warning.assert_not_called()
    mock_log.error.assert_not_called()


@patch("offkai_bot.alerts.task._log")
async def test_send_message_task_success_thread(mock_log, mock_client, mock_thread):
    """Test SendMessageTask successfully sends to a Thread."""
    # Arrange
    channel_id = mock_thread.id
    message_content = "Hello Thread!"
    task = SendMessageTask(client=mock_client, channel_id=channel_id, message=message_content)
    mock_client.get_channel.return_value = mock_thread

    # Act
    await task.action()

    # Assert
    mock_client.get_channel.assert_called_once_with(channel_id)
    mock_thread.send.assert_awaited_once_with(message_content)
    mock_log.debug.assert_called_once_with(f"Executing SendMessageTask for channel {channel_id}")
    mock_log.warning.assert_not_called()
    mock_log.error.assert_not_called()


@patch("offkai_bot.alerts.task._log")
async def test_send_message_task_channel_not_found(mock_log, mock_client):
    """Test SendMessageTask handles channel not found."""
    # Arrange
    channel_id = 11111
    message_content = "Doesn't matter"
    task = SendMessageTask(client=mock_client, channel_id=channel_id, message=message_content)
    mock_client.get_channel.return_value = None  # Simulate channel not found

    # Act
    await task.action()

    # Assert
    mock_client.get_channel.assert_called_once_with(channel_id)
    mock_log.warning.assert_called_once_with(f"SendMessageTask: Channel {channel_id} not found.")
    mock_log.error.assert_not_called()
    # Ensure send was not attempted on None
    # (No easy way to assert mock_text_channel.send wasn't called without having the mock)


@patch("offkai_bot.alerts.task._log")
async def test_send_message_task_wrong_channel_type(mock_log, mock_client, mock_other_channel):
    """Test SendMessageTask handles incorrect channel type."""
    # Arrange
    channel_id = mock_other_channel.id
    message_content = "Doesn't matter"
    task = SendMessageTask(client=mock_client, channel_id=channel_id, message=message_content)
    mock_client.get_channel.return_value = mock_other_channel

    # Act
    await task.action()

    # Assert
    mock_client.get_channel.assert_called_once_with(channel_id)
    mock_log.warning.assert_called_once_with(
        f"SendMessageTask: Channel {channel_id} is not a text channel or thread (Type: {type(mock_other_channel)})."
    )
    mock_log.error.assert_not_called()


@patch("offkai_bot.alerts.task._log")
async def test_send_message_task_send_http_error(mock_log, mock_client, mock_text_channel):
    """Test SendMessageTask handles discord.HTTPException during send."""
    # Arrange
    channel_id = mock_text_channel.id
    message_content = "Will fail"
    task = SendMessageTask(client=mock_client, channel_id=channel_id, message=message_content)
    mock_client.get_channel.return_value = mock_text_channel
    send_error = discord.HTTPException(MagicMock(), "Send failed")
    mock_text_channel.send.side_effect = send_error

    # Act
    await task.action()

    # Assert
    mock_client.get_channel.assert_called_once_with(channel_id)
    mock_text_channel.send.assert_awaited_once_with(message_content)
    mock_log.error.assert_called_once_with(
        f"SendMessageTask failed to send message to channel {channel_id}: {send_error}"
    )


@patch("offkai_bot.alerts.task._log")
async def test_send_message_task_send_unexpected_error(mock_log, mock_client, mock_text_channel):
    """Test SendMessageTask handles unexpected Exception during send."""
    # Arrange
    channel_id = mock_text_channel.id
    message_content = "Will fail unexpectedly"
    task = SendMessageTask(client=mock_client, channel_id=channel_id, message=message_content)
    mock_client.get_channel.return_value = mock_text_channel
    send_error = ValueError("Unexpected send issue")
    mock_text_channel.send.side_effect = send_error

    # Act
    await task.action()

    # Assert
    mock_client.get_channel.assert_called_once_with(channel_id)
    mock_text_channel.send.assert_awaited_once_with(message_content)
    mock_log.exception.assert_called_once_with(
        f"Unexpected error in SendMessageTask for channel {channel_id}: {send_error}"
    )


# --- Tests for CloseOffkaiTask ---


# Patch the perform_close_event function *where it's looked up* by task.py
@patch("offkai_bot.alerts.task.perform_close_event", new_callable=AsyncMock)
@patch("offkai_bot.alerts.task._log")
async def test_close_offkai_task_success(mock_log, mock_perform_close, mock_client):
    """Test CloseOffkaiTask successfully calls perform_close_event."""
    # Arrange
    event_name = "Event To Close"
    task = CloseOffkaiTask(client=mock_client, event_name=event_name)
    # Default close_msg is used

    # Act
    await task.action()

    # Assert
    mock_perform_close.assert_awaited_once_with(
        mock_client,
        event_name,
        task.close_msg,  # Check default message is passed
    )
    mock_log.info.assert_any_call(f"Executing CloseOffkaiTask for event: '{event_name}'")
    mock_log.info.assert_any_call(f"Successfully executed automatic closure for event: '{event_name}'")
    mock_log.log.assert_not_called()
    mock_log.error.assert_not_called()
    mock_log.exception.assert_not_called()


@patch("offkai_bot.alerts.task.perform_close_event", new_callable=AsyncMock)
@patch("offkai_bot.alerts.task._log")
async def test_close_offkai_task_handles_bot_command_error(mock_log, mock_perform_close, mock_client):
    """Test CloseOffkaiTask handles BotCommandError from perform_close_event."""
    # Arrange
    event_name = "Missing Event"
    task = CloseOffkaiTask(client=mock_client, event_name=event_name)
    # Simulate EventNotFoundError (which inherits from BotCommandError)
    error_to_raise = EventNotFoundError(event_name)
    # Assign a specific log level to the error instance for testing
    error_to_raise.log_level = logging.WARNING
    mock_perform_close.side_effect = error_to_raise

    # Act
    await task.action()

    # Assert
    mock_perform_close.assert_awaited_once_with(mock_client, event_name, task.close_msg)
    mock_log.info.assert_called_once_with(f"Executing CloseOffkaiTask for event: '{event_name}'")  # Only start log
    # Check that the specific error log was called with the correct level
    mock_log.log.assert_called_once_with(
        logging.WARNING,  # Check the level assigned to the error instance
        f"Error during automatic closure of '{event_name}': {error_to_raise}",
    )
    mock_log.error.assert_not_called()
    mock_log.exception.assert_not_called()


@patch("offkai_bot.alerts.task.perform_close_event", new_callable=AsyncMock)
@patch("offkai_bot.alerts.task._log")
async def test_close_offkai_task_handles_http_exception(mock_log, mock_perform_close, mock_client):
    """Test CloseOffkaiTask handles discord.HTTPException from perform_close_event."""
    # Arrange
    event_name = "Event With API Error"
    task = CloseOffkaiTask(client=mock_client, event_name=event_name)
    error_to_raise = discord.HTTPException(MagicMock(), "Discord API failed")
    mock_perform_close.side_effect = error_to_raise

    # Act
    await task.action()

    # Assert
    mock_perform_close.assert_awaited_once_with(mock_client, event_name, task.close_msg)
    mock_log.info.assert_called_once_with(f"Executing CloseOffkaiTask for event: '{event_name}'")
    mock_log.error.assert_called_once_with(
        f"Discord API error during automatic closure of '{event_name}': {error_to_raise}"
    )
    mock_log.log.assert_not_called()  # Check specific log level wasn't used
    mock_log.exception.assert_not_called()


@patch("offkai_bot.alerts.task.perform_close_event", new_callable=AsyncMock)
@patch("offkai_bot.alerts.task._log")
async def test_close_offkai_task_handles_unexpected_exception(mock_log, mock_perform_close, mock_client):
    """Test CloseOffkaiTask handles generic Exception from perform_close_event."""
    # Arrange
    event_name = "Event With Unexpected Error"
    task = CloseOffkaiTask(client=mock_client, event_name=event_name)
    error_to_raise = ValueError("Something completely unexpected happened")
    mock_perform_close.side_effect = error_to_raise

    # Act
    await task.action()

    # Assert
    mock_perform_close.assert_awaited_once_with(mock_client, event_name, task.close_msg)
    mock_log.info.assert_called_once_with(f"Executing CloseOffkaiTask for event: '{event_name}'")
    mock_log.exception.assert_called_once_with(
        f"Unexpected error during automatic closure of '{event_name}': {error_to_raise}"
    )
    mock_log.log.assert_not_called()
    mock_log.error.assert_not_called()
