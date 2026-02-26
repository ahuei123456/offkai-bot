# tests/commands/test_archive_offkai.py

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
    EventAlreadyArchivedError,
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
    interaction.command.name = "archive_offkai"

    # Mock response methods
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock(send=AsyncMock())  # In case response is done

    return interaction


@pytest.fixture
def mock_archived_event_obj(sample_event_list):
    """
    Fixture providing an Event object representing the state *after* archiving.
    Based on 'Summer Bash' from sample_event_list.
    """
    # Find the original 'Summer Bash' event
    original_event = next(e for e in sample_event_list if e.event_name == "Summer Bash")
    # Create a copy and modify the status
    archived_event = Event(**original_event.__dict__)  # Simple copy for dataclass
    archived_event.archived = True
    archived_event.open = False  # Archiving also closes
    return archived_event


# --- Test Cases ---


# --- UPDATED PATCHES ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.archive_event")
@patch("offkai_bot.cogs.events._log")
async def test_archive_offkai_success(
    mock_log,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,  # Renamed from mock_client
    mock_interaction,
    mock_thread,  # From conftest.py
    mock_archived_event_obj,  # From this file
    prepopulated_event_cache,
    mock_cog,
):
    # --- END UPDATED PATCHES ---
    """Test the successful path of archive_offkai."""
    # Arrange
    event_name_to_archive = "Summer Bash"

    mock_archive_event_func.return_value = mock_archived_event_obj
    # Mock the helper returning the thread
    mock_fetch_thread.return_value = mock_thread
    # Ensure thread ID matches event ID if needed
    mock_thread.id = mock_archived_event_obj.channel_id
    mock_thread.mention = f"<#{mock_thread.id}>"
    mock_thread.archived = False  # Ensure thread starts not archived

    # Act
    await EventsCog.archive_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert
    mock_archive_event_func.assert_called_once_with(event_name_to_archive)
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once_with(ANY, mock_archived_event_obj)  # ANY for client
    # Check fetching the thread via helper
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_archived_event_obj)  # ANY for client
    # Check archiving the Discord thread
    mock_thread.edit.assert_awaited_once_with(archived=True, locked=True)
    # Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )
    mock_log.info.assert_called()
    mock_log.warning.assert_not_called()


@pytest.mark.parametrize(
    "error_type, error_args",
    [
        (EventNotFoundError, ("NonExistent Event",)),
        (EventAlreadyArchivedError, ("Archived Party",)),  # Use the already archived event
    ],
)
# --- UPDATED PATCHES ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.archive_event")
@patch("offkai_bot.cogs.events._log")
async def test_archive_offkai_data_layer_errors(
    mock_log,
    mock_archive_event_func,
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
    """Test handling of errors raised by archive_event data layer function."""
    # Arrange
    event_name = error_args[0]
    mock_archive_event_func.side_effect = error_type(*error_args)

    # Act & Assert
    with pytest.raises(error_type):
        await EventsCog.archive_offkai.callback(
            mock_cog,
            mock_interaction,
            event_name=event_name,
        )

    mock_archive_event_func.assert_called_once()
    mock_save_data.assert_not_called()
    mock_update_msg_view.assert_not_awaited()
    mock_fetch_thread.assert_not_awaited()  # Check helper wasn't called
    mock_interaction.response.send_message.assert_not_awaited()


# --- UPDATED TEST ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.archive_event")
@patch("offkai_bot.cogs.events._log")
async def test_archive_offkai_fetch_thread_not_found_error(  # Renamed test
    mock_log,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,  # Renamed from mock_client
    mock_interaction,
    mock_archived_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test archive_offkai when fetch_thread_for_event raises ThreadNotFoundError."""
    # Arrange
    event_name_to_archive = "Summer Bash"
    mock_archive_event_func.return_value = mock_archived_event_obj
    # Mock the helper raising the error
    mock_fetch_thread.side_effect = ThreadNotFoundError(event_name_to_archive, mock_archived_event_obj.channel_id)

    # Act
    await EventsCog.archive_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert
    # Steps up to fetching thread should succeed
    mock_archive_event_func.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_archived_event_obj)

    # Editing thread should be skipped, warning logged
    mock_log.log.assert_called_once()
    assert mock_log.log.call_args[0][0] == logging.WARNING  # Default level for ThreadNotFoundError
    assert f"Could not archive thread for event '{event_name_to_archive}'" in mock_log.log.call_args[0][1]
    assert "Could not find thread channel" in mock_log.log.call_args[0][1]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )


# --- END UPDATED TEST ---


# --- NEW TEST ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.archive_event")
@patch("offkai_bot.cogs.events._log")
async def test_archive_offkai_fetch_thread_missing_id_error(
    mock_log,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_interaction,
    mock_archived_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test archive_offkai when fetch_thread_for_event raises MissingChannelIDError."""
    # Arrange
    event_name_to_archive = "Summer Bash"
    mock_archive_event_func.return_value = mock_archived_event_obj
    mock_fetch_thread.side_effect = MissingChannelIDError(event_name_to_archive)

    # Act
    await EventsCog.archive_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert
    mock_archive_event_func.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_archived_event_obj)

    # Editing thread should be skipped, warning logged
    mock_log.log.assert_called_once()
    assert mock_log.log.call_args[0][0] == logging.WARNING  # Default level for MissingChannelIDError
    assert f"Could not archive thread for event '{event_name_to_archive}'" in mock_log.log.call_args[0][1]
    assert "does not have a channel ID" in mock_log.log.call_args[0][1]

    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )


# --- END NEW TEST ---


# --- NEW TEST ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.archive_event")
@patch("offkai_bot.cogs.events._log")
async def test_archive_offkai_fetch_thread_access_error(
    mock_log,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_interaction,
    mock_archived_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test archive_offkai when fetch_thread_for_event raises ThreadAccessError."""
    # Arrange
    event_name_to_archive = "Summer Bash"
    mock_archive_event_func.return_value = mock_archived_event_obj
    mock_fetch_thread.side_effect = ThreadAccessError(event_name_to_archive, mock_archived_event_obj.channel_id)

    # Act
    await EventsCog.archive_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert
    mock_archive_event_func.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_archived_event_obj)

    # Editing thread should be skipped, error logged
    mock_log.log.assert_called_once()
    assert mock_log.log.call_args[0][0] == logging.ERROR  # Check level for ThreadAccessError
    assert f"Could not archive thread for event '{event_name_to_archive}'" in mock_log.log.call_args[0][1]
    assert "Bot lacks permissions" in mock_log.log.call_args[0][1]

    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )


# --- END NEW TEST ---


# --- UPDATED PATCHES ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.archive_event")
@patch("offkai_bot.cogs.events._log")
async def test_archive_offkai_thread_already_archived(
    mock_log,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,  # Renamed from mock_client
    mock_interaction,
    mock_thread,  # Need thread mock
    mock_archived_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    # --- END UPDATED PATCHES ---
    """Test archive_offkai when the Discord thread is already archived."""
    # Arrange
    event_name_to_archive = "Summer Bash"
    mock_archive_event_func.return_value = mock_archived_event_obj
    # Mock helper returning thread successfully
    mock_fetch_thread.return_value = mock_thread
    mock_thread.archived = True  # Simulate thread already archived

    # Act
    await EventsCog.archive_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert
    mock_archive_event_func.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    # Assert helper was called
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_archived_event_obj)

    # Editing thread should be skipped because thread.archived is True
    mock_thread.edit.assert_not_awaited()
    mock_log.warning.assert_not_called()  # No warning needed if already archived

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )


# --- UPDATED PATCHES ---
@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.archive_event")
@patch("offkai_bot.cogs.events._log")
async def test_archive_offkai_thread_edit_fails(
    mock_log,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,  # Renamed from mock_client
    mock_interaction,
    mock_thread,  # Need the thread mock here
    mock_archived_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    # --- END UPDATED PATCHES ---
    """Test archive_offkai when editing the thread fails."""
    # Arrange
    event_name_to_archive = "Summer Bash"
    mock_archive_event_func.return_value = mock_archived_event_obj
    # Mock helper returning thread successfully
    mock_fetch_thread.return_value = mock_thread
    mock_thread.archived = False  # Ensure thread starts not archived
    # Simulate error editing thread
    edit_error = discord.HTTPException(MagicMock(), "Cannot edit thread")
    mock_thread.edit.side_effect = edit_error

    # Act
    await EventsCog.archive_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert
    mock_archive_event_func.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    # Assert helper was called
    mock_fetch_thread.assert_awaited_once_with(ANY, mock_archived_event_obj)
    # Assert edit was called
    mock_thread.edit.assert_awaited_once_with(archived=True, locked=True)

    # Warning should be logged for edit failure
    mock_log.warning.assert_called_once()
    assert f"Could not archive thread {mock_thread.id}" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )


@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.archive_event")
@patch("offkai_bot.cogs.events._log")
async def test_archive_offkai_deletes_role(
    mock_log,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_interaction,
    mock_thread,
    mock_archived_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test that archive_offkai deletes the participant role if it exists."""
    # Arrange
    event_name_to_archive = "Summer Bash"
    mock_archived_event_obj.role_id = 99999

    mock_archive_event_func.return_value = mock_archived_event_obj
    mock_fetch_thread.return_value = mock_thread
    mock_thread.archived = False

    mock_role = MagicMock(spec=discord.Role)
    mock_role.delete = AsyncMock()
    mock_interaction.guild.get_role.return_value = mock_role

    # Act
    await EventsCog.archive_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert
    mock_interaction.guild.get_role.assert_called_once_with(99999)
    mock_role.delete.assert_awaited_once_with(reason=f"Offkai '{event_name_to_archive}' archived")
    mock_log.info.assert_any_call(f"Deleted participant role 99999 for archived event '{event_name_to_archive}'.")
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )


@patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.save_event_data")
@patch("offkai_bot.cogs.events.archive_event")
@patch("offkai_bot.cogs.events._log")
async def test_archive_offkai_role_deletion_failure_non_fatal(
    mock_log,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_fetch_thread,
    mock_interaction,
    mock_thread,
    mock_archived_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test that archive_offkai still succeeds if role deletion fails."""
    # Arrange
    event_name_to_archive = "Summer Bash"
    mock_archived_event_obj.role_id = 99999

    mock_archive_event_func.return_value = mock_archived_event_obj
    mock_fetch_thread.return_value = mock_thread
    mock_thread.archived = False

    mock_role = MagicMock(spec=discord.Role)
    mock_role.delete = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Missing Permissions"))
    mock_interaction.guild.get_role.return_value = mock_role

    # Act
    await EventsCog.archive_offkai.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert — role deletion was attempted but failed
    mock_role.delete.assert_awaited_once()
    mock_log.warning.assert_called()
    warning_msg = mock_log.warning.call_args_list[-1][0][0]
    assert f"Failed to delete participant role for '{event_name_to_archive}'" in warning_msg
    # Archive still succeeds
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )
