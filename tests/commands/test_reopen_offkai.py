# tests/commands/test_reopen_offkai.py

import logging
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

# Import the function to test and relevant errors/classes
from offkai_bot.cogs.events import EventsCog
from offkai_bot.data.event import Event  # To create return value
from offkai_bot.errors import (
    EventAlreadyOpenError,
    EventArchivedError,
    EventNotFoundError,
    MissingChannelIDError,
    ThreadAccessError,
    ThreadNotFoundError,
)

# pytest marker for async tests
pytestmark = pytest.mark.asyncio

# --- Fixtures ---


@pytest.fixture
def mock_cog():
    """Fixture to create a mock EventsCog instance."""
    bot = MagicMock(spec=commands.Bot)
    return EventsCog(bot)


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
    reopened_event = Event(**original_event.__dict__)  # Simple copy for dataclass
    reopened_event.open = True  # Set to open
    return reopened_event


# --- Test Cases ---


# --- UPDATED PATCHES ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.set_event_open_status")
@patch("offkai_bot.cogs.events._log")
async def test_reopen_offkai_success_with_message(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,  # Renamed from mock_client
    mock_interaction,
    mock_thread,  # From conftest.py
    mock_reopened_event,  # From this file
    prepopulated_event_cache,
    mock_cog,
):
    # --- END UPDATED PATCHES ---
    """Test the successful path of reopen_offkai with a reopening message."""
    # Arrange
    event_name_to_reopen = "Autumn Meetup"
    reopen_text = "Responses are now open again!"

    mock_set_status.return_value = mock_reopened_event
    # Mock the helper returning the thread
    mock_fetch_thread.return_value = mock_thread
    # Ensure thread ID matches event ID if needed
    mock_thread.id = mock_reopened_event.channel_id
    mock_thread.mention = f"<#{mock_thread.id}>"

    # Act
    await EventsCog.reopen_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_reopen,
        reopen_msg=reopen_text,
    )

    # Assert
    mock_set_status.assert_called_once_with(event_name_to_reopen, target_open_status=True)
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once_with(ANY, mock_reopened_event)  # ANY for client
    # Check fetching the thread via helper
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_reopened_event)  # ANY for client
    # Check sending reopening message to thread
    mock_thread.send.assert_awaited_once_with(f"**Responses Reopened:**\n{reopen_text}")
    # Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_reopen}' have been reopened."
    )
    mock_log.warning.assert_not_called()


# --- UPDATED PATCHES ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.set_event_open_status")
@patch("offkai_bot.cogs.events._log")
async def test_reopen_offkai_success_no_message(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,  # Renamed from mock_client
    mock_interaction,
    mock_thread,
    mock_reopened_event,
    prepopulated_event_cache,
    mock_cog,
):
    # --- END UPDATED PATCHES ---
    """Test the successful path of reopen_offkai without a reopening message."""
    # Arrange
    event_name_to_reopen = "Autumn Meetup"
    mock_set_status.return_value = mock_reopened_event

    # Act
    await EventsCog.reopen_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_reopen,
        reopen_msg=None,  # Explicitly None
    )

    # Assert
    mock_set_status.assert_called_once_with(event_name_to_reopen, target_open_status=True)
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once_with(ANY, mock_reopened_event)
    # Check fetching the thread was NOT called (because reopen_msg is None)
    mock_fetch_thread.assert_not_awaited()
    # Check sending reopening message was NOT called
    mock_thread.send.assert_not_awaited()
    # Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_reopen}' have been reopened."
    )
    mock_log.warning.assert_not_called()


@pytest.mark.parametrize(
    "error_type, error_args",
    [
        (EventNotFoundError, ("NonExistent Event",)),
        (EventArchivedError, ("Archived Party", "open")),
        (EventAlreadyOpenError, ("Summer Bash",)),  # Use an already open event
    ],
)
# --- UPDATED PATCHES ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.set_event_open_status")
@patch("offkai_bot.cogs.events._log")
async def test_reopen_offkai_data_layer_errors(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,  # Renamed from mock_client
    mock_interaction,
    error_type,
    error_args,
    prepopulated_event_cache,
    mock_cog,
):
    # --- END UPDATED PATCHES ---
    """Test handling of errors raised by set_event_open_status when reopening."""
    # Arrange
    event_name = error_args[0]
    mock_set_status.side_effect = error_type(*error_args)

    # Act & Assert
    with pytest.raises(error_type):
        await EventsCog.reopen_offkai.callback(
            mock_cog,
            mock_interaction,
            event_name=event_name,
            reopen_msg="Attempting to reopen",
        )

    mock_set_status.assert_called_once()
    mock_save_data.assert_not_called()
    mock_update_msg_view.assert_not_awaited()
    mock_fetch_thread.assert_not_awaited()  # Check helper wasn't called
    mock_interaction.response.send_message.assert_not_awaited()


# --- UPDATED TEST ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.set_event_open_status")
@patch("offkai_bot.cogs.events._log")
async def test_reopen_offkai_fetch_thread_not_found_error(  # Renamed test
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,  # Renamed from mock_client
    mock_interaction,
    mock_reopened_event,
    prepopulated_event_cache,
    mock_cog,
):
    """Test reopen_offkai when fetch_thread_for_event raises ThreadNotFoundError."""
    # Arrange
    event_name_to_reopen = "Autumn Meetup"
    reopen_text = "Reopening!"
    mock_set_status.return_value = mock_reopened_event
    # Mock the helper raising the error
    mock_fetch_thread.side_effect = ThreadNotFoundError(event_name_to_reopen, mock_reopened_event.channel_id)

    # Act
    await EventsCog.reopen_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_reopen,
        reopen_msg=reopen_text,
    )

    # Assert
    # Steps up to fetching thread should succeed
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_reopened_event)

    # Sending update message should be skipped, warning logged
    mock_log.log.assert_called_once()
    assert mock_log.log.call_args[0][0] == logging.WARNING  # Default level for ThreadNotFoundError
    assert f"Could not send reopening message for event '{event_name_to_reopen}'" in mock_log.log.call_args[0][1]
    assert "Could not find thread channel" in mock_log.log.call_args[0][1]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_reopen}' have been reopened."
    )


# --- END UPDATED TEST ---


# --- NEW TEST ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.set_event_open_status")
@patch("offkai_bot.cogs.events._log")
async def test_reopen_offkai_fetch_thread_missing_id_error(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_interaction,
    mock_reopened_event,
    prepopulated_event_cache,
    mock_cog,
):
    """Test reopen_offkai when fetch_thread_for_event raises MissingChannelIDError."""
    # Arrange
    event_name_to_reopen = "Autumn Meetup"
    reopen_text = "Reopening!"
    mock_set_status.return_value = mock_reopened_event
    mock_fetch_thread.side_effect = MissingChannelIDError(event_name_to_reopen)

    # Act
    await EventsCog.reopen_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_reopen,
        reopen_msg=reopen_text,
    )

    # Assert
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_reopened_event)

    # Sending update message should be skipped, warning logged
    mock_log.log.assert_called_once()
    assert mock_log.log.call_args[0][0] == logging.WARNING  # Default level for MissingChannelIDError
    assert f"Could not send reopening message for event '{event_name_to_reopen}'" in mock_log.log.call_args[0][1]
    assert "does not have a channel ID" in mock_log.log.call_args[0][1]

    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_reopen}' have been reopened."
    )


# --- END NEW TEST ---


# --- NEW TEST ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.set_event_open_status")
@patch("offkai_bot.cogs.events._log")
async def test_reopen_offkai_fetch_thread_access_error(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_interaction,
    mock_reopened_event,
    prepopulated_event_cache,
    mock_cog,
):
    """Test reopen_offkai when fetch_thread_for_event raises ThreadAccessError."""
    # Arrange
    event_name_to_reopen = "Autumn Meetup"
    reopen_text = "Reopening!"
    mock_set_status.return_value = mock_reopened_event
    mock_fetch_thread.side_effect = ThreadAccessError(event_name_to_reopen, mock_reopened_event.channel_id)

    # Act
    await EventsCog.reopen_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_reopen,
        reopen_msg=reopen_text,
    )

    # Assert
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_reopened_event)

    # Sending update message should be skipped, error logged
    mock_log.log.assert_called_once()
    assert mock_log.log.call_args[0][0] == logging.ERROR  # Check level for ThreadAccessError
    assert f"Could not send reopening message for event '{event_name_to_reopen}'" in mock_log.log.call_args[0][1]
    assert "Bot lacks permissions" in mock_log.log.call_args[0][1]

    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_reopen}' have been reopened."
    )


# --- END NEW TEST ---


# --- UPDATED PATCHES ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.set_event_open_status")
@patch("offkai_bot.cogs.events._log")
async def test_reopen_offkai_send_reopen_msg_fails(
    mock_log,
    mock_set_status,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,  # Renamed from mock_client
    mock_interaction,
    mock_thread,  # Need the thread mock here
    mock_reopened_event,
    prepopulated_event_cache,
    mock_cog,
):
    # --- END UPDATED PATCHES ---
    """Test reopen_offkai when sending the reopening message fails."""
    # Arrange
    event_name_to_reopen = "Autumn Meetup"
    reopen_text = "Reopening!"
    mock_set_status.return_value = mock_reopened_event
    # Mock helper returning thread successfully
    mock_fetch_thread.return_value = mock_thread
    # Simulate error sending message
    send_error = discord.HTTPException(MagicMock(), "Cannot send messages")
    mock_thread.send.side_effect = send_error

    # Act
    await EventsCog.reopen_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_reopen,
        reopen_msg=reopen_text,
    )

    # Assert
    mock_set_status.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    # Assert helper was called
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_reopened_event)
    # Assert send was called
    mock_thread.send.assert_awaited_once_with(f"**Responses Reopened:**\n{reopen_text}")

    # Warning should be logged for send failure
    mock_log.warning.assert_called_once()
    assert f"Could not send reopening message to thread {mock_thread.id}" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Responses for '{event_name_to_reopen}' have been reopened."
    )
