# tests/test_event_actions.py

import logging
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import discord
import pytest

# Import the function to test and relevant errors/classes
from offkai_bot.data.event import Event  # To create return value
from offkai_bot.errors import (
    EventAlreadyClosedError,
    EventArchivedError,
    EventNotFoundError,
    MissingChannelIDError,
    ThreadAccessError,
    ThreadNotFoundError,
)
from offkai_bot.event_actions import perform_close_event  # <-- Function under test

# pytest marker for async tests
pytestmark = pytest.mark.asyncio

# --- Fixtures ---


@pytest.fixture
def mock_client():
    """Fixture to create a mock discord.Client."""
    client = MagicMock(spec=discord.Client)
    # Add any specific client methods needed by the functions called within perform_close_event
    # For now, fetch_thread_for_event is mocked directly, so client methods aren't strictly needed here.
    return client


# mock_thread fixture is assumed to be in conftest.py
# sample_event_list fixture is assumed to be in conftest.py
# prepopulated_event_cache fixture is assumed to be in conftest.py


@pytest.fixture
def mock_closed_event(sample_event_list):
    """
    Fixture providing an Event object representing the state *after* closing.
    Based on 'Summer Bash' from sample_event_list.
    """
    # Find the original 'Summer Bash' event
    original_event = next((e for e in sample_event_list if e.event_name == "Summer Bash"), None)
    if original_event is None:
        pytest.fail("Could not find 'Summer Bash' in sample_event_list fixture")

    # Create a copy and modify the 'open' status
    closed_event = Event(**original_event.__dict__)  # Simple copy for dataclass
    closed_event.open = False
    return closed_event


# --- Test Cases ---


# Patches target the functions *as looked up within event_actions.py*
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
    mock_client,  # Fixture for client instance
    mock_thread,  # From conftest.py
    mock_closed_event,  # From this file
    prepopulated_event_cache,  # Ensure data is loaded
):
    """Test the successful path of perform_close_event with a closing message."""
    # Arrange
    event_name_to_close = "Summer Bash"
    close_text = "Responses are now closed!"

    mock_set_status.return_value = mock_closed_event
    mock_fetch_thread.return_value = mock_thread
    mock_thread.id = mock_closed_event.thread_id  # Ensure thread ID matches event
    mock_thread.mention = f"<#{mock_thread.id}>"

    # Act
    result = await perform_close_event(
        mock_client,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    assert result == mock_closed_event  # Check return value
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
    mock_thread,  # Still needed for assertions
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
        close_msg=None,  # Explicitly None
    )

    # Assert
    assert result == mock_closed_event
    mock_set_status.assert_called_once_with(event_name_to_close, target_open_status=False)
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once_with(mock_client, mock_closed_event)

    # Assert thread fetching and sending were NOT called
    mock_fetch_thread.assert_not_awaited()
    mock_thread.send.assert_not_awaited()

    # Check logs (should not log about sending message)
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
        (EventAlreadyClosedError, ("Autumn Meetup",)),  # Use an already closed event
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
    # Ensure no success logs were generated beyond the initial attempt
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
    """Test that errors during fetch_thread_for_event are caught, logged, and don't stop execution."""
    # Arrange
    event_name_to_close = error_args[0]
    close_text = "Closing!"
    mock_set_status.return_value = mock_closed_event
    mock_fetch_thread.side_effect = error_type(*error_args)

    # Act - Should complete without raising the fetch error
    result = await perform_close_event(
        mock_client,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    assert result == mock_closed_event  # Function should still return the event

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
    assert args[0] == expected_log_level  # Check log level
    assert f"Could not send closing message for event '{event_name_to_close}'" in args[1]
    assert expected_log_fragment in args[1]  # Check specific error message part


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
    """Test that errors during thread.send are caught, logged, and don't stop execution."""
    # Arrange
    event_name_to_close = "Summer Bash"
    close_text = "Closing!"
    mock_set_status.return_value = mock_closed_event
    mock_fetch_thread.return_value = mock_thread
    send_error = discord.HTTPException(MagicMock(), "Cannot send messages")
    mock_thread.send.side_effect = send_error
    mock_thread.id = mock_closed_event.thread_id

    # Act - Should complete without raising the send error
    result = await perform_close_event(
        mock_client,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    assert result == mock_closed_event  # Function should still return the event

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
    """Test that unexpected errors during thread.send are caught and logged via exception."""
    # Arrange
    event_name_to_close = "Summer Bash"
    close_text = "Closing!"
    mock_set_status.return_value = mock_closed_event
    mock_fetch_thread.return_value = mock_thread
    send_error = ValueError("Something unexpected broke")  # Non-HTTPException
    mock_thread.send.side_effect = send_error
    mock_thread.id = mock_closed_event.thread_id

    # Act - Should complete without raising the send error
    result = await perform_close_event(
        mock_client,
        event_name=event_name_to_close,
        close_msg=close_text,
    )

    # Assert
    assert result == mock_closed_event  # Function should still return the event

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
