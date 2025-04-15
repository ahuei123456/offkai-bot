# tests/commands/test_delete_response.py

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands

# Import the function to test and relevant errors/classes
from offkai_bot import main
from offkai_bot.errors import (
    EventNotFoundError,
    ResponseNotFoundError,
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
    interaction.command.name = "delete_response"

    # Mock response methods
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock(send=AsyncMock())  # In case response is done

    return interaction


@pytest.fixture
def mock_member():
    """Fixture for the target discord.Member whose response is deleted."""
    member = MagicMock(spec=discord.Member)
    member.id = 98765
    member.mention = "<@98765>"
    member.__str__.return_value = "TargetUser#5678"
    return member


@pytest.fixture
def mock_event_obj(sample_event_list):
    """Fixture providing a specific Event object (e.g., Summer Bash)."""
    # Find the 'Summer Bash' event which has channel_id 1001
    return next(e for e in sample_event_list if e.event_name == "Summer Bash")


# --- Test Cases ---


@patch("offkai_bot.main.remove_response")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main.client")  # Mock the client object to mock get_channel
@patch("offkai_bot.main._log")
async def test_delete_response_success(
    mock_log,
    mock_client,
    mock_get_event,
    mock_remove_response_func,  # Renamed mock for clarity
    mock_interaction,
    mock_member,
    mock_thread,  # From conftest.py
    mock_event_obj,  # From this file
    prepopulated_event_cache,  # Use fixture to ensure cache is populated
):
    """Test the successful path of delete_response including thread removal."""
    # Arrange
    event_name_target = "Summer Bash"

    mock_get_event.return_value = mock_event_obj
    # remove_response now returns None on success, or raises error
    # No need to set return_value explicitly if None is acceptable

    mock_client.get_channel.return_value = mock_thread
    # Ensure thread ID matches event channel ID
    mock_thread.id = mock_event_obj.channel_id
    mock_thread.mention = f"<#{mock_thread.id}>"

    # Act
    await main.delete_response.callback(
        mock_interaction,
        event_name=event_name_target,
        member=mock_member,
    )

    # Assert
    # 1. Check get_event call
    mock_get_event.assert_called_once_with(event_name_target)
    # 2. Check remove_response call
    mock_remove_response_func.assert_called_once_with(event_name_target, mock_member.id)
    # 3. Check interaction response
    mock_interaction.response.send_message.assert_awaited_once_with(
        f"🚮 Deleted response from user {mock_member.mention} for '{event_name_target}'.",
        ephemeral=True,
    )
    # 4. Check getting the channel
    mock_client.get_channel.assert_called_once_with(mock_event_obj.channel_id)
    # 5. Check removing user from thread
    mock_thread.remove_user.assert_awaited_once_with(mock_member)
    # 6. Check logs
    mock_log.info.assert_called()
    assert f"Removed user {mock_member.id} from thread {mock_thread.id}" in mock_log.info.call_args[0][0]
    mock_log.warning.assert_not_called()
    mock_log.error.assert_not_called()  # Check no error logs


@patch("offkai_bot.main.remove_response")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_delete_response_success_no_channel_id(
    mock_log,
    mock_client,
    mock_get_event,
    mock_remove_response_func,
    mock_interaction,
    mock_member,
    mock_thread,  # Still needed for potential calls if logic changed
    mock_event_obj,
    prepopulated_event_cache,
):
    """Test successful response deletion when event has no channel_id."""
    # Arrange
    event_name_target = "Summer Bash"
    mock_event_obj.channel_id = None  # Modify event for this test
    mock_get_event.return_value = mock_event_obj
    # remove_response returns None on success

    # Act
    await main.delete_response.callback(
        mock_interaction,
        event_name=event_name_target,
        member=mock_member,
    )

    # Assert
    # Steps up to response should succeed
    mock_get_event.assert_called_once_with(event_name_target)
    mock_remove_response_func.assert_called_once_with(event_name_target, mock_member.id)
    mock_interaction.response.send_message.assert_awaited_once()

    # Discord interactions should be skipped, warning logged
    mock_client.get_channel.assert_not_called()
    mock_thread.remove_user.assert_not_awaited()
    mock_log.warning.assert_called_once()
    assert f"Event '{event_name_target}' is missing channel_id" in mock_log.warning.call_args[0][0]
    mock_log.info.assert_called_once()
    mock_log.error.assert_not_called()


@patch("offkai_bot.main.remove_response")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_delete_response_success_thread_not_found(
    mock_log,
    mock_client,
    mock_get_event,
    mock_remove_response_func,
    mock_interaction,
    mock_member,
    mock_thread,
    mock_event_obj,
    prepopulated_event_cache,
):
    """Test successful response deletion when thread is not found."""
    # Arrange
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj
    # remove_response returns None on success
    mock_client.get_channel.return_value = None  # Simulate thread not found

    # Act
    await main.delete_response.callback(
        mock_interaction,
        event_name=event_name_target,
        member=mock_member,
    )

    # Assert
    # Steps up to response should succeed
    mock_get_event.assert_called_once_with(event_name_target)
    mock_remove_response_func.assert_called_once_with(event_name_target, mock_member.id)
    mock_interaction.response.send_message.assert_awaited_once()
    mock_client.get_channel.assert_called_once_with(mock_event_obj.channel_id)

    # Removing user should be skipped, warning logged
    mock_thread.remove_user.assert_not_awaited()
    mock_log.warning.assert_called_once()
    assert f"Could not find thread {mock_event_obj.channel_id}" in mock_log.warning.call_args[0][0]
    mock_log.info.assert_called_once()
    mock_log.error.assert_not_called()


@patch("offkai_bot.main.remove_response")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_delete_response_success_remove_user_fails(
    mock_log,
    mock_client,
    mock_get_event,
    mock_remove_response_func,
    mock_interaction,
    mock_member,
    mock_thread,
    mock_event_obj,
    prepopulated_event_cache,
):
    """Test successful response deletion when thread.remove_user fails (error logged)."""
    # Arrange
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj
    # remove_response returns None on success
    mock_client.get_channel.return_value = mock_thread
    # Simulate error removing user
    remove_error = discord.HTTPException(MagicMock(), "Cannot remove user")
    mock_thread.remove_user.side_effect = remove_error

    # Act
    await main.delete_response.callback(
        mock_interaction,
        event_name=event_name_target,
        member=mock_member,
    )

    # Assert
    # Steps up to remove_user should succeed
    mock_get_event.assert_called_once_with(event_name_target)
    mock_remove_response_func.assert_called_once_with(event_name_target, mock_member.id)
    mock_interaction.response.send_message.assert_awaited_once()
    mock_client.get_channel.assert_called_once_with(mock_event_obj.channel_id)
    mock_thread.remove_user.assert_awaited_once_with(mock_member)  # Should still be called

    # Error should be logged, no warning/info logs expected for this specific part
    mock_log.error.assert_called_once()
    assert f"Failed to remove user {mock_member.id}" in mock_log.error.call_args[0][0]
    mock_log.warning.assert_not_called()
    mock_log.info.assert_called_once()


@patch("offkai_bot.main.remove_response")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_delete_response_event_not_found(
    mock_log,
    mock_client,
    mock_get_event,
    mock_remove_response_func,
    mock_interaction,
    mock_member,
    prepopulated_event_cache,  # Still useful for setup/teardown
):
    """Test delete_response when the initial get_event fails."""
    # Arrange
    event_name_target = "NonExistent Event"
    mock_get_event.side_effect = EventNotFoundError(event_name_target)

    # Act & Assert
    with pytest.raises(EventNotFoundError):
        await main.delete_response.callback(
            mock_interaction,
            event_name=event_name_target,
            member=mock_member,
        )

    # Assert only get_event was called
    mock_get_event.assert_called_once_with(event_name_target)
    mock_remove_response_func.assert_not_called()
    mock_interaction.response.send_message.assert_not_awaited()
    mock_client.get_channel.assert_not_called()


@patch("offkai_bot.main.remove_response")
@patch("offkai_bot.main.get_event")
@patch("offkai_bot.main.client")
@patch("offkai_bot.main._log")
async def test_delete_response_response_not_found_in_data(
    mock_log,
    mock_client,
    mock_get_event,
    mock_remove_response_func,
    mock_interaction,
    mock_member,
    mock_event_obj,
    mock_thread,
    prepopulated_event_cache,
):
    """Test delete_response when remove_response raises ResponseNotFoundError."""
    # Arrange
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj
    # Simulate remove_response raising the error
    mock_remove_response_func.side_effect = ResponseNotFoundError(event_name_target, mock_member.id)

    # Act & Assert
    with pytest.raises(ResponseNotFoundError) as exc_info:
        await main.delete_response.callback(
            mock_interaction,
            event_name=event_name_target,
            member=mock_member,
        )

    # Assert error details (check user_id now)
    assert exc_info.value.event_name == event_name_target
    assert exc_info.value.user_id == mock_member.id  # Check user_id

    # Assert calls up to remove_response
    mock_get_event.assert_called_once_with(event_name_target)
    mock_remove_response_func.assert_called_once_with(event_name_target, mock_member.id)

    # Assert subsequent steps were NOT called
    mock_interaction.response.send_message.assert_not_awaited()
    mock_client.get_channel.assert_not_called()
    mock_thread.remove_user.assert_not_awaited()  # Ensure thread removal wasn't attempted
