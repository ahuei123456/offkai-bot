import logging
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

# Import the function to test and relevant errors/classes
from offkai_bot.data.event import Event
from offkai_bot.errors import (
    EventAlreadyClosedError,
    EventArchivedError,
    EventNotFoundError,
    MissingChannelIDError,
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
@patch("offkai_bot.event_actions.ClosedEvent")
@patch("offkai_bot.event_actions.OpenEvent")
@patch("offkai_bot.event_actions._log")
async def test_send_event_message_sends_and_pins_for_open_event(
    mock_log,
    mock_open_event_view,
    mock_closed_event_view,
    mock_create_message,
    mock_save_data,
    mock_thread,
    mock_event,
):
    """Verify that send_event_message sends, pins, and saves for an OPEN event."""
    # Arrange
    message_content = "Test message for an open event"
    mock_create_message.return_value = message_content

    # Mock the Message object that channel.send will return
    mock_message = AsyncMock(spec=discord.Message)
    mock_message.id = 998877
    mock_thread.send.return_value = mock_message

    # Configure the event to be open
    mock_event.open = True
    mock_event.event_name = "Test Open Event"

    # Act
    await send_event_message(mock_thread, mock_event)

    # Assert
    # 1. Verify the correct view was created for an open event
    mock_open_event_view.assert_called_once_with(mock_event)
    mock_closed_event_view.assert_not_called()

    # 2. Verify the message was sent with the correct content and view
    mock_thread.send.assert_awaited_once_with(message_content, view=mock_open_event_view.return_value)

    # 3. **Verify the message was pinned**
    mock_message.pin.assert_awaited_once_with(reason=None)

    # 4. Verify the event object was updated and saved
    assert mock_event.message_id == mock_message.id
    mock_save_data.assert_called_once()

    # 5. Verify a success log was written
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

    # Configure the event to be closed
    mock_event.open = False
    mock_event.event_name = "Test Closed Event"

    # Act
    await send_event_message(mock_thread, mock_event)

    # Assert
    # 1. Verify the correct view was created for a closed event
    mock_closed_event_view.assert_called_once_with(mock_event)
    mock_open_event_view.assert_not_called()

    # 2. Verify the message was sent with the correct content and view
    mock_thread.send.assert_awaited_once_with(message_content, view=mock_closed_event_view.return_value)

    # 3. **Verify the message was pinned**
    mock_message.pin.assert_awaited_once_with(reason=None)

    # 4. Verify the event object was updated and saved
    assert mock_event.message_id == mock_message.id
    mock_save_data.assert_called_once()

    # 5. Verify a success log was written
    mock_log.info.assert_called_once()


@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.create_event_message")
@patch("offkai_bot.event_actions.OpenEvent")
@patch("offkai_bot.event_actions._log")
async def test_send_event_message_does_not_pin_on_send_failure(
    mock_log,
    mock_open_event_view,
    mock_create_message,
    mock_save_data,
    mock_thread,
    mock_event,
):
    """Verify that message pinning and data saving do not occur if channel.send fails."""
    # Arrange
    mock_create_message.return_value = "This message will fail to send"

    # Simulate discord.py raising an error on send
    http_error = discord.HTTPException(MagicMock(), "Test send failure")
    mock_thread.send.side_effect = http_error

    mock_event.open = True
    mock_event.event_name = "Test Failing Event"
    # Ensure message_id is None or some other value before the call
    mock_event.message_id = None

    # Act
    await send_event_message(mock_thread, mock_event)

    # Assert
    # 1. Verify that sending was attempted
    mock_thread.send.assert_awaited_once()

    # 2. **Verify that pinning, saving, and updating were NOT performed**
    assert mock_event.message_id is None
    mock_save_data.assert_not_called()

    # 3. Verify an error was logged and the info log was skipped
    mock_log.error.assert_called_once()
    mock_log.info.assert_not_called()


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

    # Check logs
    mock_log.info.assert_any_call(f"Attempting to close event '{event_name_to_close}'...")
    mock_log.info.assert_any_call(f"Event '{event_name_to_close}' status set to closed and data saved.")
    mock_log.info.assert_any_call(f"Updated persistent message for event '{event_name_to_close}'.")
    mock_log.info.assert_any_call(f"Sent closing message to thread {mock_thread.id} for event '{event_name_to_close}'.")
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

    # Assert thread fetching and sending were NOT called
    mock_fetch_thread.assert_not_awaited()
    mock_thread.send.assert_not_awaited()

    # Check logs
    mock_log.info.assert_any_call(f"Attempting to close event '{event_name_to_close}'...")
    mock_log.info.assert_any_call(f"Event '{event_name_to_close}' status set to closed and data saved.")
    mock_log.info.assert_any_call(f"Updated persistent message for event '{event_name_to_close}'.")
    mock_log.info.assert_any_call(f"No closing message provided for event '{event_name_to_close}'.")
    mock_log.warning.assert_not_called()
    mock_log.error.assert_not_called()


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

    # Only set_status should have been called
    mock_set_status.assert_called_once_with(event_name, target_open_status=False)
    mock_save_data.assert_not_called()
    mock_update_msg_view.assert_not_awaited()
    mock_fetch_thread.assert_not_awaited()
    mock_log.info.assert_any_call(f"Attempting to close event '{event_name}'...")
    assert mock_log.info.call_count == 1


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

    # Steps up to update_message should have been called
    mock_set_status.assert_called_once_with(event_name_to_close, target_open_status=False)
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once_with(mock_client, mock_closed_event)
    # Fetch thread should NOT have been called as the error occurred before it
    mock_fetch_thread.assert_not_awaited()


@pytest.mark.parametrize(
    "error_type, error_args, expected_log_level, expected_log_fragment",
    [
        (
            MissingChannelIDError,
            ("Summer Bash",),
            logging.WARNING,
            "does not have a channel ID",
        ),
        (
            ThreadNotFoundError,
            ("Summer Bash", 12345),
            logging.WARNING,
            "Could not find thread channel",
        ),
        (
            ThreadAccessError,
            ("Summer Bash", 12345),
            logging.ERROR,
            "Bot lacks permissions",
        ),
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

    # Steps up to fetching thread should succeed
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(mock_client, mock_closed_event)

    # Sending message to thread should be skipped
    mock_thread.send.assert_not_awaited()

    # Check that the specific error was logged correctly
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

    # All steps including fetch and send attempt should have occurred
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(mock_client, mock_closed_event)
    mock_thread.send.assert_awaited_once_with(f"**Responses Closed:**\n{close_text}")

    # Warning should be logged for send failure
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

    # All steps including fetch and send attempt should have occurred
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(mock_client, mock_closed_event)
    mock_thread.send.assert_awaited_once_with(f"**Responses Closed:**\n{close_text}")

    # Error should be logged via exception
    mock_log.exception.assert_called_once()
    assert (
        f"Unexpected error sending closing message for event '{event_name_to_close}'"
        in mock_log.exception.call_args[0][0]
    )
