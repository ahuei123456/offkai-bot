# tests/test_error_handler.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import discord
from discord import app_commands
import logging

# --- Updated Imports ---
# Import from the 'offkai_bot' package located within 'src'
from offkai_bot import main  # Import the module containing on_command_error
from offkai_bot import errors  # Import your custom error classes

# --- End Updated Imports ---

# pytest marker for async tests
pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_interaction():
    """Creates a reusable mock discord.Interaction object for tests."""
    # Create a mock interaction object
    interaction = MagicMock(spec=discord.Interaction)

    # Mock user details
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 1234567890
    interaction.user.name = "TestUser"
    interaction.user.__str__.return_value = "TestUser#1234"  # For logging format

    # Mock context details
    interaction.guild_id = 9876543210
    interaction.channel_id = 1122334455

    # Mock the command attribute
    interaction.command = MagicMock(spec=app_commands.Command)
    interaction.command.name = "mock_command"

    # Mock the response methods (crucially, make them AsyncMock)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done.return_value = (
        False  # Default: interaction not yet responded to
    )

    # Mock the followup methods
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    # Mock guild/role lookup if needed for MissingRole test refinement
    mock_guild = MagicMock(spec=discord.Guild)
    mock_role = MagicMock(spec=discord.Role, name="Offkai Organizer")
    mock_guild.get_role.return_value = mock_role
    interaction.guild = mock_guild  # Assign mock guild to interaction

    return interaction


# --- Test Cases ---


async def test_on_command_error_missing_role(mock_interaction):
    """Test handling of app_commands.MissingRole."""
    # Arrange
    # Assuming the check uses the role name/ID directly from config,
    # but the error handler might try to fetch the role name for the message.
    # The fixture now mocks interaction.guild.get_role.
    error = app_commands.MissingRole(
        "Offkai Organizer"
    )  # Role name/ID used by the check

    # --- Updated Patch Target ---
    with patch("offkai_bot.main._log") as mock_log:
        # Act
        await main.on_command_error(mock_interaction, error)

        # Assert: Check response
        # The error handler uses the role name "Offkai Organizer" directly
        expected_message = "❌ You need the Offkai Organizer role to use this command."
        mock_interaction.response.send_message.assert_awaited_once_with(
            expected_message, ephemeral=True
        )
        mock_interaction.followup.send.assert_not_called()  # Should not use followup

        # Assert: Check logging
        mock_log.warning.assert_called_once()
        log_call_args = mock_log.warning.call_args[0][
            0
        ]  # Get the first positional arg of the call
        assert (
            "Missing Offkai Organizer role" in log_call_args
        )  # Check specific role name
        assert "User: TestUser#1234 (1234567890)" in log_call_args
        assert "command 'mock_command'" in log_call_args


async def test_on_command_error_check_failure(mock_interaction):
    """Test handling of generic app_commands.CheckFailure."""
    # Arrange
    error = app_commands.CheckFailure("Some check failed")

    # --- Updated Patch Target ---
    with patch("offkai_bot.main._log") as mock_log:
        # Act
        await main.on_command_error(mock_interaction, error)

        # Assert: Check response
        expected_message = "❌ You do not have permission to use this command."
        mock_interaction.response.send_message.assert_awaited_once_with(
            expected_message, ephemeral=True
        )
        mock_interaction.followup.send.assert_not_called()

        # Assert: Check logging
        mock_log.warning.assert_called_once()
        log_call_args = mock_log.warning.call_args[0][0]
        assert "CheckFailure for command 'mock_command'" in log_call_args
        assert "User: TestUser#1234 (1234567890)" in log_call_args


# --- Parametrized Test for Custom BotCommandErrors ---
@pytest.mark.parametrize(
    "error_class, error_args, expected_log_level, expected_log_level_name_in_msg",
    [
        # INFO level examples
        (
            errors.EventNotFound,
            ("MyMissingEvent",),
            logging.INFO,
            "Handled (EventNotFound)",
        ),
        (
            errors.DuplicateEventError,
            ("ExistingEvent",),
            logging.INFO,
            "Handled (DuplicateEventError)",
        ),
        (
            errors.InvalidDateTimeFormat,
            (),
            logging.INFO,
            "Handled (InvalidDateTimeFormat)",
        ),
        (
            errors.NoChangesProvidedError,
            (),
            logging.INFO,
            "Handled (NoChangesProvidedError)",
        ),
        # WARNING level examples
        (
            errors.ThreadNotFoundError,
            ("MyEvent", 999888777),
            logging.WARNING,
            "Handled (ThreadNotFoundError)",
        ),
        (
            errors.MissingChannelIDError,
            ("EventWithoutChannel",),
            logging.WARNING,
            "Handled (MissingChannelIDError)",
        ),
        (
            errors.InvalidChannelTypeError,
            ("DM Channel",),
            logging.WARNING,
            "Handled (InvalidChannelTypeError)",
        ),
        (
            errors.BroadcastPermissionError,
            (
                MagicMock(spec=discord.Thread, mention="<#123>"),
                MagicMock(spec=discord.Forbidden),
            ),
            logging.WARNING,
            "Handled (BroadcastPermissionError)",
        ),
    ],
)
async def test_on_command_error_custom_bot_error(
    mock_interaction,
    error_class,
    error_args,
    expected_log_level,
    expected_log_level_name_in_msg,
):
    """Tests handling of various BotCommandError subclasses and their log levels."""
    # Arrange
    original_error = error_class(*error_args)
    error = app_commands.CommandInvokeError(mock_interaction.command, original_error)

    with patch("offkai_bot.main._log") as mock_log:
        # Act
        await main.on_command_error(mock_interaction, error)

        # Assert: Check response
        expected_message = str(original_error)
        mock_interaction.response.send_message.assert_awaited_once_with(
            expected_message, ephemeral=True
        )
        mock_interaction.followup.send.assert_not_called()

        # Assert: Check logging using _log.log()
        mock_log.log.assert_called_once()
        call_args, call_kwargs = mock_log.log.call_args

        # Assert the log level passed to _log.log()
        assert call_args[0] == expected_log_level

        # Assert the content of the log message
        log_message = call_args[1]
        assert (
            expected_log_level_name_in_msg in log_message
        )  # Check type name indication
        assert f": {expected_message}" in log_message  # Check the error's message
        assert "User: TestUser#1234 (1234567890)" in log_message

        # Assert specific level loggers were NOT called directly
        mock_log.info.assert_not_called()
        mock_log.warning.assert_not_called()
        mock_log.error.assert_not_called()


async def test_on_command_error_discord_forbidden(mock_interaction):
    """Test handling of discord.Forbidden (usually wrapped)."""
    # Arrange
    mock_response = MagicMock()
    mock_response.status = 403
    mock_response.reason = "Forbidden"
    original_error = discord.Forbidden(mock_response, "Missing Permissions")
    error = app_commands.CommandInvokeError(mock_interaction.command, original_error)

    with patch("offkai_bot.main._log") as mock_log:
        # Act
        await main.on_command_error(mock_interaction, error)

        # Assert: Check response
        expected_message = "❌ The bot lacks permissions to perform this action."
        mock_interaction.response.send_message.assert_awaited_once_with(
            expected_message, ephemeral=True
        )

        # Assert: Check logging (still uses direct .warning())
        mock_log.warning.assert_called_once()
        log_call_args = mock_log.warning.call_args[0][0]
        assert "Encountered discord.Forbidden" in log_call_args
        mock_log.log.assert_not_called()  # Ensure .log() wasn't used for this case


async def test_on_command_error_unhandled_exception(mock_interaction):
    """Test handling of an unexpected exception."""
    # Arrange
    original_error = ValueError("Something completely unexpected happened")
    error = app_commands.CommandInvokeError(mock_interaction.command, original_error)

    with patch("offkai_bot.main._log") as mock_log:
        # Act
        await main.on_command_error(mock_interaction, error)

        # Assert: Check response
        expected_message = "❌ An unexpected error occurred. Please try again later or contact an admin."
        mock_interaction.response.send_message.assert_awaited_once_with(
            expected_message, ephemeral=True
        )

        # Assert: Check logging (still uses direct .error())
        mock_log.error.assert_called_once()
        log_call_args = mock_log.error.call_args[0][0]
        log_call_kwargs = mock_log.error.call_args[1]
        assert "Unhandled command error" in log_call_args
        assert log_call_kwargs.get("exc_info") is original_error
        mock_log.log.assert_not_called()  # Ensure .log() wasn't used for this case


async def test_on_command_error_interaction_already_done(mock_interaction):
    """Test error handling when interaction.response.is_done() is True."""
    # Arrange
    original_error = errors.EventNotFound(
        "AnotherMissingEvent"
    )  # Example using INFO level
    error = app_commands.CommandInvokeError(mock_interaction.command, original_error)
    mock_interaction.response.is_done.return_value = True

    with patch("offkai_bot.main._log") as mock_log:
        # Act
        await main.on_command_error(mock_interaction, error)

        # Assert: Check response uses followup
        expected_message = str(original_error)
        mock_interaction.followup.send.assert_awaited_once_with(
            expected_message, ephemeral=True
        )
        mock_interaction.response.send_message.assert_not_called()

        # Assert: Check logging still happens correctly using _log.log()
        mock_log.log.assert_called_once()
        call_args, _ = mock_log.log.call_args
        assert call_args[0] == logging.INFO  # Check the level
        log_message = call_args[1]
        assert (
            f"Handled (EventNotFound): {expected_message}" in log_message
        )  # Check content


async def test_on_command_error_fails_sending_response(mock_interaction):
    """Test when sending the error response itself fails."""
    # Arrange
    original_error = errors.EventNotFound("EventToSendFail")  # Example using INFO level
    error = app_commands.CommandInvokeError(mock_interaction.command, original_error)
    send_error = discord.HTTPException(MagicMock(), "Failed to send")
    mock_interaction.response.send_message.side_effect = send_error

    with patch("offkai_bot.main._log") as mock_log:
        # Act
        await main.on_command_error(mock_interaction, error)

        # Assert: Check that the original error was logged via _log.log()
        mock_log.log.assert_called_once()
        call_args, _ = mock_log.log.call_args
        assert call_args[0] == logging.INFO  # Check level for handled error
        log_message = call_args[1]
        assert f"Handled (EventNotFound): {str(original_error)}" in log_message

        # Assert: Check that the failure during sending was logged (still uses direct .error())
        mock_log.error.assert_called_once()
        log_call_args = mock_log.error.call_args[0][0]
        assert "Failed to send error response message" in log_call_args
        assert str(send_error) in log_call_args

        # Assert: Ensure followup wasn't attempted if response failed
        mock_interaction.followup.send.assert_not_called()


async def test_on_command_error_no_command_context(mock_interaction):
    """Test error handling when interaction.command is None."""
    # Arrange
    mock_interaction.command = None  # Explicitly set command to None
    error = app_commands.CheckFailure("Check failed without command context")

    with patch("offkai_bot.main._log") as mock_log:
        # Act
        await main.on_command_error(mock_interaction, error)

        # Assert: Check response is still sent
        expected_message = "❌ You do not have permission to use this command."
        mock_interaction.response.send_message.assert_awaited_once_with(
            expected_message, ephemeral=True
        )

        # Assert: Check logging uses "Unknown"
        mock_log.warning.assert_called_once()
        log_call_args = mock_log.warning.call_args[0][0]
        assert (
            "CheckFailure for command 'Unknown'" in log_call_args
        )  # Verify fallback name
        assert "User: TestUser#1234 (1234567890)" in log_call_args
