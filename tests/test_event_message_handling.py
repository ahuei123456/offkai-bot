# tests/test_event_message_handling.py

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

# Import module and functions under test
from offkai_bot import interactions
from offkai_bot.data.event import Event
from offkai_bot.errors import (
    MissingChannelIDError,
    ThreadAccessError,
    ThreadNotFoundError,
)

# pytest marker for async tests
pytestmark = pytest.mark.asyncio

# --- Fixtures ---


@pytest.fixture
def mock_client():
    """Fixture for a mock discord.Client."""
    client = MagicMock(spec=discord.Client)
    client.get_channel = MagicMock()
    client.fetch_channel = AsyncMock()
    return client


@pytest.fixture
def mock_message():
    """Fixture for a mock discord.Message."""
    message = MagicMock(spec=discord.Message)
    message.id = 55555
    message.edit = AsyncMock()
    return message


# Use events from conftest sample_event_list where possible
@pytest.fixture
def mock_event_open(sample_event_list):
    """An open, non-archived event with IDs."""
    return next(e for e in sample_event_list if e.event_name == "Summer Bash")


@pytest.fixture
def mock_event_closed(sample_event_list):
    """A closed, non-archived event with IDs."""
    return next(e for e in sample_event_list if e.event_name == "Autumn Meetup")


@pytest.fixture
def mock_event_archived(sample_event_list):
    """An archived event."""
    return next(e for e in sample_event_list if e.event_name == "Archived Party")


@pytest.fixture
def mock_event_no_ids(sample_event_list):
    """An event missing channel/message IDs."""
    event = next(e for e in sample_event_list if e.event_name == "Summer Bash")
    event_copy = Event(**event.__dict__)
    event_copy.channel_id = None
    event_copy.thread_id = None
    event_copy.message_id = None
    return event_copy


# --- Tests for fetch_thread_for_event ---


@patch("offkai_bot.interactions._log")
async def test_fetch_thread_success_get_channel(mock_log, mock_client, mock_thread, mock_event_open):
    """Test fetch_thread_for_event success using client.get_channel."""
    mock_client.get_channel.return_value = mock_thread
    mock_event_open.thread_id = mock_thread.id  # Ensure ID matches

    thread = await interactions.fetch_thread_for_event(mock_client, mock_event_open)

    assert thread is mock_thread
    mock_client.get_channel.assert_called_once_with(mock_event_open.thread_id)
    mock_client.fetch_channel.assert_not_awaited()
    mock_log.error.assert_not_called()


@patch("offkai_bot.interactions._log")
async def test_fetch_thread_success_fetch_channel(mock_log, mock_client, mock_thread, mock_event_open):
    """Test fetch_thread_for_event success using client.fetch_channel fallback."""
    mock_client.get_channel.return_value = None  # Simulate cache miss
    mock_client.fetch_channel.return_value = mock_thread
    mock_event_open.thread_id = mock_thread.id

    thread = await interactions.fetch_thread_for_event(mock_client, mock_event_open)

    assert thread is mock_thread
    mock_client.get_channel.assert_called_once_with(mock_event_open.thread_id)
    mock_client.fetch_channel.assert_awaited_once_with(mock_event_open.thread_id)
    mock_log.debug.assert_called_once()  # Check debug log for fallback


@patch("offkai_bot.interactions._log")
async def test_fetch_thread_missing_id(mock_log, mock_client, mock_event_no_ids):
    """Test fetch_thread_for_event raises MissingChannelIDError."""
    with pytest.raises(MissingChannelIDError) as exc_info:
        await interactions.fetch_thread_for_event(mock_client, mock_event_no_ids)

    assert exc_info.value.event_name == mock_event_no_ids.event_name
    mock_client.get_channel.assert_not_called()
    mock_client.fetch_channel.assert_not_awaited()


@patch("offkai_bot.interactions._log")
async def test_fetch_thread_not_found_fetch(mock_log, mock_client, mock_event_open):
    """Test fetch_thread_for_event raises ThreadNotFoundError on fetch_channel NotFound."""
    mock_client.get_channel.return_value = None
    mock_client.fetch_channel.side_effect = discord.errors.NotFound(MagicMock(), "not found")

    with pytest.raises(ThreadNotFoundError) as exc_info:
        await interactions.fetch_thread_for_event(mock_client, mock_event_open)

    assert exc_info.value.event_name == mock_event_open.event_name
    assert exc_info.value.thread_id == mock_event_open.thread_id
    mock_client.get_channel.assert_called_once()
    mock_client.fetch_channel.assert_awaited_once()


@patch("offkai_bot.interactions._log")
async def test_fetch_thread_forbidden_fetch(mock_log, mock_client, mock_event_open):
    """Test fetch_thread_for_event raises ThreadAccessError on fetch_channel Forbidden."""
    mock_client.get_channel.return_value = None
    error = discord.errors.Forbidden(MagicMock(), "forbidden")
    mock_client.fetch_channel.side_effect = error

    with pytest.raises(ThreadAccessError) as exc_info:
        await interactions.fetch_thread_for_event(mock_client, mock_event_open)

    assert exc_info.value.event_name == mock_event_open.event_name
    assert exc_info.value.thread_id == mock_event_open.thread_id
    assert exc_info.value.original_exception is error
    mock_client.get_channel.assert_called_once()
    mock_client.fetch_channel.assert_awaited_once()


@patch("offkai_bot.interactions._log")
async def test_fetch_thread_wrong_type(mock_log, mock_client, mock_event_open):
    """Test fetch_thread_for_event raises ThreadNotFoundError for wrong channel type."""
    wrong_channel = MagicMock(spec=discord.TextChannel)  # Not a Thread
    mock_client.get_channel.return_value = wrong_channel

    with pytest.raises(ThreadNotFoundError) as exc_info:
        await interactions.fetch_thread_for_event(mock_client, mock_event_open)

    assert exc_info.value.event_name == mock_event_open.event_name
    assert exc_info.value.thread_id == mock_event_open.thread_id
    mock_client.get_channel.assert_called_once()
    mock_client.fetch_channel.assert_not_awaited()


# --- Tests for _fetch_event_message ---


@patch("offkai_bot.interactions._log")
async def test_fetch_message_success(mock_log, mock_thread, mock_message, mock_event_open):
    """Test _fetch_event_message success."""
    mock_event_open.message_id = mock_message.id
    mock_thread.fetch_message.return_value = mock_message

    message = await interactions._fetch_event_message(mock_thread, mock_event_open)

    assert message is mock_message
    mock_thread.fetch_message.assert_awaited_once_with(mock_event_open.message_id)
    mock_log.debug.assert_called_once()
    mock_log.warning.assert_not_called()
    mock_log.error.assert_not_called()


@patch("offkai_bot.interactions._log")
async def test_fetch_message_no_id(mock_log, mock_thread, mock_event_no_ids):
    """Test _fetch_event_message when event has no message_id."""
    message = await interactions._fetch_event_message(mock_thread, mock_event_no_ids)
    assert message is None
    mock_thread.fetch_message.assert_not_awaited()


@patch("offkai_bot.interactions._log")
async def test_fetch_message_not_found(mock_log, mock_thread, mock_event_open):
    """Test _fetch_event_message when fetch_message raises NotFound."""
    original_id = 12345
    mock_event_open.message_id = original_id
    mock_thread.fetch_message.side_effect = discord.errors.NotFound(MagicMock(), "not found")

    message = await interactions._fetch_event_message(mock_thread, mock_event_open)

    assert message is None
    assert mock_event_open.message_id is None  # Check ID was cleared
    mock_thread.fetch_message.assert_awaited_once_with(original_id)
    mock_log.warning.assert_called_once()
    assert f"Message ID {original_id} not found" in mock_log.warning.call_args[0][0]


@patch("offkai_bot.interactions._log")
async def test_fetch_message_forbidden(mock_log, mock_thread, mock_event_open):
    """Test _fetch_event_message when fetch_message raises Forbidden."""
    original_id = 12345
    mock_event_open.message_id = original_id
    mock_thread.fetch_message.side_effect = discord.errors.Forbidden(MagicMock(), "forbidden")

    message = await interactions._fetch_event_message(mock_thread, mock_event_open)

    assert message is None
    assert mock_event_open.message_id == original_id  # ID should NOT be cleared
    mock_thread.fetch_message.assert_awaited_once_with(original_id)
    mock_log.error.assert_called_once()
    assert "Bot lacks permissions to fetch message" in mock_log.error.call_args[0][0]


@patch("offkai_bot.interactions._log")
async def test_fetch_message_http_error(mock_log, mock_thread, mock_event_open):
    """Test _fetch_event_message when fetch_message raises HTTPException."""
    original_id = 12345
    mock_event_open.message_id = original_id
    mock_thread.fetch_message.side_effect = discord.HTTPException(MagicMock(), "http error")

    message = await interactions._fetch_event_message(mock_thread, mock_event_open)

    assert message is None
    assert mock_event_open.message_id == original_id  # ID should NOT be cleared
    mock_thread.fetch_message.assert_awaited_once_with(original_id)
    mock_log.error.assert_called_once()
    assert "HTTP error fetching message" in mock_log.error.call_args[0][0]


# --- Tests for send_event_message ---


@patch("offkai_bot.interactions.save_event_data")
@patch("offkai_bot.interactions.create_event_message")
@patch("offkai_bot.interactions._log")
async def test_send_message_success_open(
    mock_log, mock_create_msg, mock_save, mock_thread, mock_message, mock_event_open
):
    """Test send_event_message success for an open event."""
    mock_content = "Test Message Content Open"
    mock_create_msg.return_value = mock_content
    mock_thread.send.return_value = mock_message  # Mock send returning the message

    await interactions.send_event_message(mock_thread, mock_event_open)

    mock_create_msg.assert_called_once_with(mock_event_open)
    # Check view type passed to send
    call_args, call_kwargs = mock_thread.send.call_args
    assert call_args[0] == mock_content
    assert isinstance(call_kwargs["view"], interactions.OpenEvent)
    # Check message ID was set and saved
    assert mock_event_open.message_id == mock_message.id
    mock_save.assert_called_once()
    mock_log.info.assert_called_once()


@patch("offkai_bot.interactions.save_event_data")
@patch("offkai_bot.interactions.create_event_message")
@patch("offkai_bot.interactions._log")
async def test_send_message_success_closed(
    mock_log, mock_create_msg, mock_save, mock_thread, mock_message, mock_event_closed
):
    """Test send_event_message success for a closed event."""
    mock_content = "Test Message Content Closed"
    mock_create_msg.return_value = mock_content
    mock_thread.send.return_value = mock_message

    await interactions.send_event_message(mock_thread, mock_event_closed)

    mock_create_msg.assert_called_once_with(mock_event_closed)
    # Check view type passed to send
    call_args, call_kwargs = mock_thread.send.call_args
    assert call_args[0] == mock_content
    assert isinstance(call_kwargs["view"], interactions.ClosedEvent)
    # Check message ID was set and saved
    assert mock_event_closed.message_id == mock_message.id
    mock_save.assert_called_once()
    mock_log.info.assert_called_once()


@patch("offkai_bot.interactions.save_event_data")
@patch("offkai_bot.interactions.create_event_message")
@patch("offkai_bot.interactions._log")
async def test_send_message_http_error(mock_log, mock_create_msg, mock_save, mock_thread, mock_event_open):
    """Test send_event_message handles HTTPException during send."""
    mock_create_msg.return_value = "Content"
    mock_thread.send.side_effect = discord.HTTPException(MagicMock(), "Send failed")

    await interactions.send_event_message(mock_thread, mock_event_open)

    mock_thread.send.assert_awaited_once()
    mock_save.assert_not_called()  # Save should not happen on error
    mock_log.error.assert_called_once()
    assert "Failed to send event message" in mock_log.error.call_args[0][0]


# --- Tests for update_event_message ---


@patch("offkai_bot.interactions.send_event_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions._fetch_event_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.interactions.create_event_message")
@patch("offkai_bot.interactions._log")
async def test_update_message_success_edit(
    mock_log,
    mock_create_msg,
    mock_fetch_thread,
    mock_fetch_msg,
    mock_send_new,
    mock_client,
    mock_thread,
    mock_message,
    mock_event_open,
):
    """Test update_event_message successfully edits an existing message."""
    mock_fetch_thread.return_value = mock_thread
    mock_fetch_msg.return_value = mock_message
    mock_content = "Updated Content"
    mock_create_msg.return_value = mock_content

    await interactions.update_event_message(mock_client, mock_event_open)

    mock_fetch_thread.assert_awaited_once_with(mock_client, mock_event_open)
    mock_fetch_msg.assert_awaited_once_with(mock_thread, mock_event_open)
    mock_create_msg.assert_called_once_with(mock_event_open)
    # Check edit was called with correct content and view
    call_args, call_kwargs = mock_message.edit.call_args
    assert call_kwargs["content"] == mock_content
    assert isinstance(call_kwargs["view"], interactions.OpenEvent)
    mock_message.edit.assert_awaited_once()
    # Check send_new was NOT called
    mock_send_new.assert_not_awaited()
    mock_log.info.assert_called_once()  # Log update success


@patch("offkai_bot.interactions.send_event_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions._fetch_event_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.interactions.create_event_message")
@patch("offkai_bot.interactions._log")
async def test_update_message_success_send_new(
    mock_log,
    mock_create_msg,
    mock_fetch_thread,
    mock_fetch_msg,
    mock_send_new,
    mock_client,
    mock_thread,
    mock_message,  # mock_message isn't strictly needed here now
    mock_event_open,  # Use the base open event fixture
):
    """Test update_event_message sends a new message if event.message_id is None."""
    # Arrange
    # --- MODIFICATION: Ensure message_id is None for this test case ---
    mock_event_open.message_id = None
    # --- END MODIFICATION ---

    mock_fetch_thread.return_value = mock_thread
    # _fetch_event_message won't actually be called if message_id is None,
    # but setting return value doesn't hurt.
    mock_fetch_msg.return_value = None
    # create_event_message is still needed by send_event_message
    mock_create_msg.return_value = "Content For New"

    # Act
    await interactions.update_event_message(mock_client, mock_event_open)

    # Assert
    mock_fetch_thread.assert_awaited_once_with(mock_client, mock_event_open)
    # _fetch_event_message should be called anyway
    mock_fetch_msg.assert_awaited_once()
    # Check edit was NOT called (mock_message fixture isn't used, but the mock exists)
    mock_message.edit.assert_not_awaited()
    # Check send_new WAS called
    mock_send_new.assert_awaited_once_with(mock_thread, mock_event_open)
    mock_log.info.assert_called()  # Log sending new


@patch("offkai_bot.interactions.send_event_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions._fetch_event_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.interactions._log")
async def test_update_message_thread_fetch_fails(
    mock_log, mock_fetch_thread, mock_fetch_msg, mock_send_new, mock_client, mock_event_open
):
    """Test update_event_message returns early if thread fetch fails."""
    error_to_raise = ThreadNotFoundError(mock_event_open.event_name, mock_event_open.channel_id)
    mock_fetch_thread.side_effect = error_to_raise

    await interactions.update_event_message(mock_client, mock_event_open)

    mock_fetch_thread.assert_awaited_once_with(mock_client, mock_event_open)
    # Check subsequent steps were skipped
    mock_fetch_msg.assert_not_awaited()
    mock_send_new.assert_not_awaited()
    # Check error was logged
    mock_log.log.assert_called_once()
    assert mock_log.log.call_args[0][0] == logging.WARNING  # Check level
    assert f"Failed to get thread for event '{mock_event_open.event_name}'" in mock_log.log.call_args[0][1]


@patch("offkai_bot.interactions.send_event_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions._fetch_event_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.interactions._log")
async def test_update_message_message_fetch_fails_perms(
    mock_log, mock_fetch_thread, mock_fetch_msg, mock_send_new, mock_client, mock_thread, mock_event_open
):
    """Test update_event_message returns early if message fetch fails (perms/HTTP)."""
    mock_fetch_thread.return_value = mock_thread
    # Simulate fetch failing but returning None (error logged internally by helper)
    mock_fetch_msg.return_value = None
    # Crucially, ensure the event *had* a message ID initially, so we know fetch failed, not just missing ID
    mock_event_open.message_id = 99999

    await interactions.update_event_message(mock_client, mock_event_open)

    mock_fetch_thread.assert_awaited_once_with(mock_client, mock_event_open)
    mock_fetch_msg.assert_awaited_once_with(mock_thread, mock_event_open)
    # Check subsequent steps were skipped
    mock_send_new.assert_not_awaited()
    # Error logging is handled inside _fetch_event_message, check log wasn't called again here
    mock_log.log.assert_not_called()  # update_event_message itself shouldn't log again


@patch("offkai_bot.interactions.send_event_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions._fetch_event_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.interactions.create_event_message")
@patch("offkai_bot.interactions._log")
async def test_update_message_edit_fails(
    mock_log,
    mock_create_msg,
    mock_fetch_thread,
    mock_fetch_msg,
    mock_send_new,
    mock_client,
    mock_thread,
    mock_message,
    mock_event_open,
):
    """Test update_event_message handles errors during message.edit."""
    mock_fetch_thread.return_value = mock_thread
    mock_fetch_msg.return_value = mock_message
    mock_create_msg.return_value = "Content"
    mock_message.edit.side_effect = discord.HTTPException(MagicMock(), "Edit failed")

    await interactions.update_event_message(mock_client, mock_event_open)

    mock_fetch_thread.assert_awaited_once()
    mock_fetch_msg.assert_awaited_once()
    mock_message.edit.assert_awaited_once()  # Edit was attempted
    mock_send_new.assert_not_awaited()  # Send new should not be called
    mock_log.error.assert_called_once()  # Error during edit should be logged
    assert f"Failed to update event message {mock_message.id}" in mock_log.error.call_args[0][0]


# --- Tests for load_and_update_events ---


@patch("offkai_bot.interactions.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.load_event_data")
@patch("offkai_bot.interactions._log")
async def test_load_and_update_events_success(
    mock_log,
    mock_load_data,
    mock_update,
    mock_client,
    mock_event_open,
    mock_event_closed,
    mock_event_archived,  # Use specific event fixtures
):
    """Test load_and_update_events calls update for non-archived events."""
    mock_events = [mock_event_open, mock_event_closed, mock_event_archived]
    mock_load_data.return_value = mock_events

    await interactions.load_and_update_events(mock_client)

    mock_load_data.assert_called_once()
    # Check update was called for open and closed, but not archived
    assert mock_update.await_count == 2
    mock_update.assert_any_await(mock_client, mock_event_open)
    mock_update.assert_any_await(mock_client, mock_event_closed)
    # Check it wasn't called with the archived one (difficult to assert directly not called with specific args)
    # Instead, rely on the await_count being correct (2 calls, not 3)
    mock_log.info.assert_called()  # Check startup/finish logs


@patch("offkai_bot.interactions.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.load_event_data")
@patch("offkai_bot.interactions._log")
async def test_load_and_update_events_no_events(mock_log, mock_load_data, mock_update, mock_client):
    """Test load_and_update_events when no events are loaded."""
    mock_load_data.return_value = []

    await interactions.load_and_update_events(mock_client)

    mock_load_data.assert_called_once()
    mock_update.assert_not_awaited()  # Update should not be called
    mock_log.info.assert_any_call("No events found to load.")
