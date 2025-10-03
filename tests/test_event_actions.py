import logging
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from offkai_bot.data.event import Event
from offkai_bot.errors import (
    EventAlreadyClosedError,
    EventArchivedError,
    EventNotFoundError,
    MissingChannelIDError,
    PinPermissionError,
    ThreadAccessError,
    ThreadNotFoundError,
)

# Functions under test
from offkai_bot.event_actions import perform_close_event, send_event_message

# pytest marker for async tests
pytestmark = pytest.mark.asyncio


# --- Fixtures ---


@pytest.fixture
def mock_client():
    """Fixture to create a mock discord.Client."""
    client = MagicMock(spec=discord.Client)
    return client


@pytest.fixture
def mock_thread():
    """Fixture for a mock discord.Thread with a send method."""
    thread = MagicMock(spec=discord.Thread)
    thread.id = 111222333
    thread.send = AsyncMock()
    return thread


@pytest.fixture
def mock_event():
    """Fixture for a generic mock Event object."""
    return MagicMock(spec=Event)


@pytest.fixture
def mock_closed_event(sample_event_list):
    """
    Fixture providing an Event object representing the state *after* closing.
    Based on 'Summer Bash' from sample_event_list.
    """
    original_event = next((e for e in sample_event_list if e.event_name == "Summer Bash"), None)
    if original_event is None:
        pytest.fail("Could not find 'Summer Bash' in sample_event_list fixture")

    closed_event = Event(**original_event.__dict__)
    closed_event.open = False
    return closed_event


# --- Tests for send_event_message ---


@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.create_event_message")
@patch("offkai_bot.event_actions.get_event_view")
@patch("offkai_bot.event_actions._log")
async def test_send_event_message_sends_and_pins_for_open_event(
    mock_log,
    mock_get_event_view,
    mock_create_message,
    mock_save_data,
    mock_thread,
    mock_event,
):
    """Verify that send_event_message sends, pins, and saves for an OPEN event."""
    # Arrange
    message_content = "Test message for an open event"
    mock_create_message.return_value = message_content
    mock_message = AsyncMock(spec=discord.Message)
    mock_message.id = 998877
    mock_thread.send.return_value = mock_message
    mock_event.open = True
    mock_event.event_name = "Test Open Event"

    # Act
    await send_event_message(mock_thread, mock_event)

    # Assert
    mock_get_event_view.assert_called_once_with(mock_event)
    mock_thread.send.assert_awaited_once_with(message_content, view=mock_get_event_view.return_value)
    mock_message.pin.assert_awaited_once_with(reason="New event message.")
    assert mock_event.message_id == mock_message.id
    mock_save_data.assert_called_once()
    mock_log.info.assert_called_once()


@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.create_event_message")
@patch("offkai_bot.event_actions.ClosedEvent")
@patch("offkai_bot.event_actions.OpenEvent")
@patch("offkai_bot.event_actions._log")
async def test_send_event_message_sends_and_pins_for_closed_event(
    mock_log,
    mock_open_event_view,
    mock_closed_event_view,
    mock_create_message,
    mock_save_data,
    mock_thread,
    mock_event,
):
    """Verify that send_event_message sends, pins, and saves for a CLOSED event."""
    # Arrange
    message_content = "Test message for a closed event"
    mock_create_message.return_value = message_content
    mock_message = AsyncMock(spec=discord.Message)
    mock_message.id = 776655
    mock_thread.send.return_value = mock_message
    mock_event.open = False
    mock_event.event_name = "Test Closed Event"

    # Act
    await send_event_message(mock_thread, mock_event)

    # Assert
    mock_closed_event_view.assert_called_once_with(mock_event)
    mock_open_event_view.assert_not_called()
    mock_thread.send.assert_awaited_once_with(message_content, view=mock_closed_event_view.return_value)
    mock_message.pin.assert_awaited_once_with(reason="New event message.")
    assert mock_event.message_id == mock_message.id
    mock_save_data.assert_called_once()
    mock_log.info.assert_called_once()


@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.create_event_message")
@patch("offkai_bot.event_actions.OpenEvent")
@patch("offkai_bot.event_actions._log")
async def test_send_event_message_http_error_on_send(
    mock_log,
    mock_open_event_view,
    mock_create_message,
    mock_save_data,
    mock_thread,
    mock_event,
):
    """Verify pinning and saving do not occur if channel.send fails with HTTPException."""
    # Arrange
    mock_create_message.return_value = "This message will fail to send"
    http_error = discord.HTTPException(MagicMock(), "Test send failure")
    mock_thread.send.side_effect = http_error
    mock_event.open = True
    mock_event.event_name = "Test Failing Event"
    mock_event.message_id = None

    # Act
    await send_event_message(mock_thread, mock_event)

    # Assert
    mock_thread.send.assert_awaited_once()
    assert mock_event.message_id is None
    mock_save_data.assert_not_called()
    mock_log.error.assert_called_once()
    # This assertion is now corrected to match the updated log message
    assert "Failed to send or pin event message" in mock_log.error.call_args[0][0]
    mock_log.info.assert_not_called()


@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.create_event_message")
@patch("offkai_bot.event_actions.OpenEvent")
@patch("offkai_bot.event_actions._log")
async def test_send_event_message_raises_on_pin_failure(
    mock_log,
    mock_open_event_view,
    mock_create_message,
    mock_save_data,
    mock_thread,
    mock_event,
):
    """Verify PinPermissionError is raised if pinning fails, but message is still saved."""
    # Arrange
    mock_create_message.return_value = "Test message"
    mock_message = AsyncMock(spec=discord.Message)
    mock_message.id = 12345
    forbidden_error = discord.Forbidden(MagicMock(), "Missing Permissions to Pin")
    mock_message.pin.side_effect = forbidden_error
    mock_thread.send.return_value = mock_message
    mock_event.open = True
    mock_event.event_name = "Test Pin Fail Event"

    # Act & Assert
    with pytest.raises(PinPermissionError) as exc_info:
        await send_event_message(mock_thread, mock_event)

    assert exc_info.value.channel is mock_thread
    assert exc_info.value.original_exception is forbidden_error
    mock_thread.send.assert_awaited_once()
    mock_message.pin.assert_awaited_once()
    assert mock_event.message_id == mock_message.id
    mock_save_data.assert_called_once()
    mock_log.info.assert_called_once()
    mock_log.error.assert_not_called()


# --- Tests for perform_close_event ---


@patch("offkai_bot.event_actions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.set_event_open_status")
@patch("offkai_bot.event_actions._log")
async def test_perform_close_event_success_with_message(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_client,
    mock_thread,
    mock_closed_event,
    prepopulated_event_cache,
):
    """Test the successful path of perform_close_event with a closing message."""
    # Arrange
    event_name_to_close = "Summer Bash"
    close_text = "Responses are now closed!"
    mock_set_status.return_value = mock_closed_event
    mock_fetch_thread.return_value = mock_thread
    mock_thread.id = mock_closed_event.thread_id
    mock_thread.mention = f"<#{mock_thread.id}>"

    # Act
    result = await perform_close_event(
        mock_client,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    assert result == mock_closed_event
    mock_set_status.assert_called_once_with(event_name_to_close, target_open_status=False)
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once_with(mock_client, mock_closed_event)
    mock_fetch_thread.assert_awaited_once_with(mock_client, mock_closed_event)
    mock_thread.send.assert_awaited_once_with(f"**Responses Closed:**\n{close_text}")
    mock_log.warning.assert_not_called()
    mock_log.error.assert_not_called()


@patch("offkai_bot.event_actions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.set_event_open_status")
@patch("offkai_bot.event_actions._log")
async def test_perform_close_event_success_no_message(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_client,
    mock_thread,
    mock_closed_event,
    prepopulated_event_cache,
):
    """Test the successful path of perform_close_event without a closing message."""
    # Arrange
    event_name_to_close = "Summer Bash"
    mock_set_status.return_value = mock_closed_event

    # Act
    result = await perform_close_event(
        mock_client,
        event_name=event_name_to_close,
        close_msg=None,
    )

    # Assert
    assert result == mock_closed_event
    mock_set_status.assert_called_once_with(event_name_to_close, target_open_status=False)
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once_with(mock_client, mock_closed_event)
    mock_fetch_thread.assert_not_awaited()
    mock_thread.send.assert_not_awaited()


@pytest.mark.parametrize(
    "error_type, error_args",
    [
        (EventNotFoundError, ("NonExistent Event",)),
        (EventArchivedError, ("Archived Party", "close")),
        (EventAlreadyClosedError, ("Autumn Meetup",)),
    ],
)
@patch("offkai_bot.event_actions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.set_event_open_status")
@patch("offkai_bot.event_actions._log")
async def test_perform_close_event_set_status_errors(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_client,
    error_type,
    error_args,
    prepopulated_event_cache,
):
    """Test that errors from set_event_open_status are propagated."""
    # Arrange
    event_name = error_args[0]
    mock_set_status.side_effect = error_type(*error_args)

    # Act & Assert
    with pytest.raises(error_type):
        await perform_close_event(
            mock_client,
            event_name=event_name,
            close_msg="Attempting to close",
        )

    mock_set_status.assert_called_once_with(event_name, target_open_status=False)
    mock_save_data.assert_not_called()
    mock_update_msg_view.assert_not_awaited()
    mock_fetch_thread.assert_not_awaited()


@patch("offkai_bot.event_actions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.set_event_open_status")
@patch("offkai_bot.event_actions._log")
async def test_perform_close_event_update_message_error(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_client,
    mock_closed_event,
    prepopulated_event_cache,
):
    """Test that errors from update_event_message are propagated."""
    # Arrange
    event_name_to_close = "Summer Bash"
    mock_set_status.return_value = mock_closed_event
    update_error = discord.HTTPException(MagicMock(), "Failed to update message")
    mock_update_msg_view.side_effect = update_error

    # Act & Assert
    with pytest.raises(discord.HTTPException, match="Failed to update message"):
        await perform_close_event(
            mock_client,
            event_name=event_name_to_close,
            close_msg="Closing",
        )

    mock_set_status.assert_called_once_with(event_name_to_close, target_open_status=False)
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once_with(mock_client, mock_closed_event)
    mock_fetch_thread.assert_not_awaited()


@pytest.mark.parametrize(
    "error_type, error_args, expected_log_level, expected_log_fragment",
    [
        (MissingChannelIDError, ("Summer Bash",), logging.WARNING, "does not have a channel ID"),
        (ThreadNotFoundError, ("Summer Bash", 12345), logging.WARNING, "Could not find thread channel"),
        (ThreadAccessError, ("Summer Bash", 12345), logging.ERROR, "Bot lacks permissions"),
    ],
)
@patch("offkai_bot.event_actions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.set_event_open_status")
@patch("offkai_bot.event_actions._log")
async def test_perform_close_event_fetch_thread_errors_handled(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_client,
    mock_thread,
    mock_closed_event,
    prepopulated_event_cache,
    error_type,
    error_args,
    expected_log_level,
    expected_log_fragment,
):
    """Test that errors during fetch_thread_for_event are caught and logged."""
    # Arrange
    event_name_to_close = error_args[0]
    close_text = "Closing!"
    mock_set_status.return_value = mock_closed_event
    mock_fetch_thread.side_effect = error_type(*error_args)

    # Act
    result = await perform_close_event(
        mock_client,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    assert result == mock_closed_event
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(mock_client, mock_closed_event)
    mock_thread.send.assert_not_awaited()

    mock_log.log.assert_called_once()
    args, kwargs = mock_log.log.call_args
    assert args[0] == expected_log_level
    assert f"Could not send closing message for event '{event_name_to_close}'" in args[1]
    assert expected_log_fragment in args[1]


@patch("offkai_bot.event_actions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.set_event_open_status")
@patch("offkai_bot.event_actions._log")
async def test_perform_close_event_send_close_msg_fails_handled(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_client,
    mock_thread,
    mock_closed_event,
    prepopulated_event_cache,
):
    """Test that errors during thread.send are caught and logged."""
    # Arrange
    event_name_to_close = "Summer Bash"
    close_text = "Closing!"
    mock_set_status.return_value = mock_closed_event
    mock_fetch_thread.return_value = mock_thread
    send_error = discord.HTTPException(MagicMock(), "Cannot send messages")
    mock_thread.send.side_effect = send_error
    mock_thread.id = mock_closed_event.thread_id

    # Act
    result = await perform_close_event(
        mock_client,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    assert result == mock_closed_event
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(mock_client, mock_closed_event)
    mock_thread.send.assert_awaited_once_with(f"**Responses Closed:**\n{close_text}")
    mock_log.warning.assert_called_once()
    assert f"Could not send closing message to thread {mock_thread.id}" in mock_log.warning.call_args[0][0]
    assert str(send_error) in mock_log.warning.call_args[0][0]


@patch("offkai_bot.event_actions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.set_event_open_status")
@patch("offkai_bot.event_actions._log")
async def test_perform_close_event_unexpected_send_error_handled(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_client,
    mock_thread,
    mock_closed_event,
    prepopulated_event_cache,
):
    """Test that unexpected errors during thread.send are caught and logged."""
    # Arrange
    event_name_to_close = "Summer Bash"
    close_text = "Closing!"
    mock_set_status.return_value = mock_closed_event
    mock_fetch_thread.return_value = mock_thread
    send_error = ValueError("Something unexpected broke")
    mock_thread.send.side_effect = send_error
    mock_thread.id = mock_closed_event.thread_id

    # Act
    result = await perform_close_event(
        mock_client,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    assert result == mock_closed_event
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(mock_client, mock_closed_event)
    mock_thread.send.assert_awaited_once_with(f"**Responses Closed:**\n{close_text}")
    mock_log.exception.assert_called_once()
    assert (
        f"Unexpected error sending closing message for event '{event_name_to_close}'"
        in mock_log.exception.call_args[0][0]
    )
