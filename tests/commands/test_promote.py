# tests/commands/test_promote.py

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from offkai_bot.cogs.events import EventsCog
from offkai_bot.errors import EventNotFoundError, ResponseNotFoundError

pytestmark = pytest.mark.asyncio


# --- Fixtures ---


@pytest.fixture
def mock_cog():
    bot = MagicMock(spec=commands.Bot)
    bot.fetch_user = AsyncMock()
    return EventsCog(bot)


@pytest.fixture
def mock_interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 123
    interaction.user.__str__.return_value = "TestUser#1234"

    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.id = 456

    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 789

    interaction.command = MagicMock(spec=app_commands.Command)
    interaction.command.name = "promote"

    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock(send=AsyncMock())

    return interaction


@pytest.fixture
def mock_event_obj(sample_event_list):
    return next(e for e in sample_event_list if e.event_name == "Summer Bash")


@pytest.fixture
def mock_waitlist_entry():
    from datetime import UTC, datetime

    from offkai_bot.data.response import WaitlistEntry

    return WaitlistEntry(
        user_id=99999,
        username="waitlistuser",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="Summer Bash",
        timestamp=datetime.now(UTC),
        drinks=[],
        extras_names=[],
        display_name="WaitlistUser",
    )


# --- Test Cases ---


@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.add_response")
@patch("offkai_bot.cogs.events.promote_specific_from_waitlist")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_promote_success(
    mock_log,
    mock_get_event,
    mock_promote_specific,
    mock_add_response,
    mock_update_event_msg,
    mock_interaction,
    mock_event_obj,
    mock_waitlist_entry,
    prepopulated_event_cache,
    mock_cog,
):
    """Test successful promotion: user promoted, DM sent, confirmation message sent."""
    mock_get_event.return_value = mock_event_obj
    mock_promote_specific.return_value = mock_waitlist_entry

    mock_promoted_user = MagicMock()
    mock_promoted_user.send = AsyncMock()
    mock_cog.bot.fetch_user.return_value = mock_promoted_user

    await EventsCog.promote.callback(
        mock_cog,
        mock_interaction,
        event_name="Summer Bash",
        username="99999",
    )

    mock_get_event.assert_called_once_with("Summer Bash")
    mock_promote_specific.assert_called_once_with("Summer Bash", 99999)
    mock_add_response.assert_called_once()

    # Verify the Response was created from the WaitlistEntry
    added_response = mock_add_response.call_args[0][1]
    assert added_response.user_id == 99999
    assert added_response.username == "waitlistuser"

    mock_interaction.response.send_message.assert_awaited_once()
    assert "Promoted user" in mock_interaction.response.send_message.call_args[0][0]
    assert mock_interaction.response.send_message.call_args[1]["ephemeral"] is True

    mock_cog.bot.fetch_user.assert_awaited_once_with(99999)
    mock_promoted_user.send.assert_awaited_once()
    mock_update_event_msg.assert_awaited_once_with(mock_cog.bot, mock_event_obj)


@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.add_response")
@patch("offkai_bot.cogs.events.promote_specific_from_waitlist")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_promote_dm_failure(
    mock_log,
    mock_get_event,
    mock_promote_specific,
    mock_add_response,
    mock_update_event_msg,
    mock_interaction,
    mock_event_obj,
    mock_waitlist_entry,
    prepopulated_event_cache,
    mock_cog,
):
    """Test that promote succeeds even if DM fails."""
    mock_get_event.return_value = mock_event_obj
    mock_promote_specific.return_value = mock_waitlist_entry

    mock_promoted_user = MagicMock()
    mock_promoted_user.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Cannot send DM"))
    mock_cog.bot.fetch_user.return_value = mock_promoted_user

    await EventsCog.promote.callback(
        mock_cog,
        mock_interaction,
        event_name="Summer Bash",
        username="99999",
    )

    # Promotion should still succeed
    mock_promote_specific.assert_called_once()
    mock_add_response.assert_called_once()
    mock_interaction.response.send_message.assert_awaited_once()
    mock_update_event_msg.assert_awaited_once()

    # DM failure should be logged as warning
    mock_log.warning.assert_called_once()
    assert "Could not DM promoted user" in mock_log.warning.call_args[0][0]


@patch("offkai_bot.cogs.events.promote_specific_from_waitlist")
@patch("offkai_bot.cogs.events.get_event")
async def test_promote_event_not_found(
    mock_get_event,
    mock_promote_specific,
    mock_interaction,
    prepopulated_event_cache,
    mock_cog,
):
    """Test that EventNotFoundError propagates."""
    mock_get_event.side_effect = EventNotFoundError("NonExistent")

    with pytest.raises(EventNotFoundError):
        await EventsCog.promote.callback(
            mock_cog,
            mock_interaction,
            event_name="NonExistent",
            username="99999",
        )

    mock_get_event.assert_called_once_with("NonExistent")
    mock_promote_specific.assert_not_called()
    mock_interaction.response.send_message.assert_not_awaited()


@patch("offkai_bot.cogs.events.add_response")
@patch("offkai_bot.cogs.events.promote_specific_from_waitlist")
@patch("offkai_bot.cogs.events.get_event")
async def test_promote_user_not_on_waitlist(
    mock_get_event,
    mock_promote_specific,
    mock_add_response,
    mock_interaction,
    mock_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test that ResponseNotFoundError propagates when user not on waitlist."""
    mock_get_event.return_value = mock_event_obj
    mock_promote_specific.side_effect = ResponseNotFoundError("Summer Bash", 99999)

    with pytest.raises(ResponseNotFoundError):
        await EventsCog.promote.callback(
            mock_cog,
            mock_interaction,
            event_name="Summer Bash",
            username="99999",
        )

    mock_promote_specific.assert_called_once_with("Summer Bash", 99999)
    mock_add_response.assert_not_called()
    mock_interaction.response.send_message.assert_not_awaited()


@patch("offkai_bot.cogs.events.promote_specific_from_waitlist")
@patch("offkai_bot.cogs.events.get_event")
async def test_promote_invalid_username(
    mock_get_event,
    mock_promote_specific,
    mock_interaction,
    mock_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test ephemeral error when username is not a valid integer."""
    mock_get_event.return_value = mock_event_obj

    await EventsCog.promote.callback(
        mock_cog,
        mock_interaction,
        event_name="Summer Bash",
        username="not_a_number",
    )

    mock_promote_specific.assert_not_called()
    mock_interaction.response.send_message.assert_awaited_once()
    call_args = mock_interaction.response.send_message.call_args
    assert "Invalid user selection" in call_args[0][0]
    assert call_args[1]["ephemeral"] is True
