# tests/commands/test_archive_offkai.py

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands

# Import the function to test and relevant errors/classes
from offkai_bot import main
from offkai_bot.data.event import Event  # To create return value
from offkai_bot.errors import (
    EventAlreadyArchivedError,
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


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.archive_event")  # Patch the correct data layer function
@patch("offkai_bot.main.client")  # Mock the client object to mock get_channel
@patch("offkai_bot.main._log")
async def test_archive_offkai_success(
    mock_log,
    mock_client,
    mock_archive_event_func,  # Renamed mock for clarity
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_thread,  # From conftest.py
    mock_archived_event_obj,  # From this file
    prepopulated_event_cache,  # Use fixture to ensure cache is populated
):
    """Test the successful path of archive_offkai."""
    # Arrange
    event_name_to_archive = "Summer Bash"  # Use an event that starts not archived

    # Mock the data layer function returning the archived event
    mock_archive_event_func.return_value = mock_archived_event_obj
    # Mock client.get_channel finding the thread
    mock_client.get_channel.return_value = mock_thread
    mock_thread.archived = False  # Ensure thread starts not archived

    # Act
    await main.archive_offkai.callback(
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert
    # 1. Check data layer call
    mock_archive_event_func.assert_called_once_with(event_name_to_archive)
    # 2. Check save call
    mock_save_data.assert_called_once()
    # 3. Check Discord message view update call
    mock_update_msg_view.assert_awaited_once_with(mock_client, mock_archived_event_obj)
    # 4. Check getting the channel
    mock_client.get_channel.assert_called_once_with(mock_archived_event_obj.channel_id)
    # 5. Check archiving the Discord thread
    mock_thread.edit.assert_awaited_once_with(archived=True, locked=True)
    # 6. Check final interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )
    # 7. Check logs (optional)
    mock_log.info.assert_called()  # Check archive log
    mock_log.warning.assert_not_called()


@pytest.mark.parametrize(
    "error_type, error_args",
    [
        (EventNotFoundError, ("NonExistent Event",)),
        (EventAlreadyArchivedError, ("Archived Party",)),  # Use the already archived event
    ],
)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.archive_event")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_archive_offkai_data_layer_errors(
    mock_log,
    mock_client,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    error_type,
    error_args,
    prepopulated_event_cache,
):
    """Test handling of errors raised by archive_event data layer function."""
    # Arrange
    event_name = error_args[0]  # Get relevant event name from args
    mock_archive_event_func.side_effect = error_type(*error_args)

    # Act & Assert
    with pytest.raises(error_type):
        await main.archive_offkai.callback(
            mock_interaction,
            event_name=event_name,
        )

    # Assert data layer call was made
    mock_archive_event_func.assert_called_once()
    # Assert subsequent steps were NOT called
    mock_save_data.assert_not_called()
    mock_update_msg_view.assert_not_awaited()
    mock_client.get_channel.assert_not_called()
    mock_interaction.response.send_message.assert_not_awaited()  # Error handler deals with response


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.archive_event")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_archive_offkai_thread_not_found(
    mock_log,
    mock_client,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_archived_event_obj,
    prepopulated_event_cache,
):
    """Test archive_offkai when the thread channel is not found."""
    # Arrange
    event_name_to_archive = "Summer Bash"
    mock_archive_event_func.return_value = mock_archived_event_obj
    mock_client.get_channel.return_value = None  # Simulate thread not found

    # Act
    await main.archive_offkai.callback(
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert
    # Steps up to finding channel should succeed
    mock_archive_event_func.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_client.get_channel.assert_called_once_with(mock_archived_event_obj.channel_id)

    # Editing thread should be skipped, warning logged
    mock_log.warning.assert_called_once()
    assert f"Could not find thread {mock_archived_event_obj.channel_id}" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.archive_event")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_archive_offkai_thread_already_archived(
    mock_log,
    mock_client,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_thread,  # Need thread mock
    mock_archived_event_obj,
    prepopulated_event_cache,
):
    """Test archive_offkai when the Discord thread is already archived."""
    # Arrange
    event_name_to_archive = "Summer Bash"
    mock_archive_event_func.return_value = mock_archived_event_obj
    mock_client.get_channel.return_value = mock_thread
    mock_thread.archived = True  # Simulate thread already archived

    # Act
    await main.archive_offkai.callback(
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert
    # Steps up to finding channel should succeed
    mock_archive_event_func.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_client.get_channel.assert_called_once_with(mock_archived_event_obj.channel_id)

    # Editing thread should be skipped because thread.archived is True
    mock_thread.edit.assert_not_awaited()
    mock_log.warning.assert_not_called()  # No warning needed if already archived

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.archive_event")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_archive_offkai_thread_edit_fails(
    mock_log,
    mock_client,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_thread,  # Need the thread mock here
    mock_archived_event_obj,
    prepopulated_event_cache,
):
    """Test archive_offkai when editing the thread fails."""
    # Arrange
    event_name_to_archive = "Summer Bash"
    mock_archive_event_func.return_value = mock_archived_event_obj
    mock_client.get_channel.return_value = mock_thread
    mock_thread.archived = False  # Ensure thread starts not archived
    # Simulate error editing thread
    edit_error = discord.HTTPException(MagicMock(), "Cannot edit thread")
    mock_thread.edit.side_effect = edit_error

    # Act
    await main.archive_offkai.callback(
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert
    # Steps up to editing thread should succeed
    mock_archive_event_func.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()
    mock_client.get_channel.assert_called_once_with(mock_archived_event_obj.channel_id)
    mock_thread.edit.assert_awaited_once_with(archived=True, locked=True)

    # Warning should be logged for edit failure
    mock_log.warning.assert_called_once()
    assert f"Could not archive thread {mock_thread.id}" in mock_log.warning.call_args[0][0]

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )


@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.main.save_event_data")
@patch("offkai_bot.main.archive_event")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_archive_offkai_missing_channel_id(
    mock_log,
    mock_client,
    mock_archive_event_func,
    mock_save_data,
    mock_update_msg_view,
    mock_interaction,
    mock_archived_event_obj,
    prepopulated_event_cache,
):
    """Test archive_offkai when the event object is missing a channel_id."""
    # Arrange
    event_name_to_archive = "Summer Bash"
    # Modify the event fixture to lack channel_id for this test
    mock_archived_event_obj.channel_id = None
    mock_archive_event_func.return_value = mock_archived_event_obj

    # Act
    await main.archive_offkai.callback(
        mock_interaction,
        event_name=event_name_to_archive,
    )

    # Assert
    # Steps up to Discord interactions should succeed
    mock_archive_event_func.assert_called_once()
    mock_save_data.assert_called_once()
    mock_update_msg_view.assert_awaited_once()

    # Getting channel and editing thread should be skipped
    mock_client.get_channel.assert_not_called()
    # No warning needed here as it's expected if channel_id is None

    # Final confirmation should still be sent
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"✅ Event '{event_name_to_archive}' has been archived."
    )
