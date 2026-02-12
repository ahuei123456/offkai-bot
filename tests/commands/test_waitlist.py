# tests/commands/test_waitlist.py

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from offkai_bot.cogs.events import EventsCog
from offkai_bot.errors import (
    EventNotFoundError,
    NoWaitlistEntriesFoundError,
)

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

    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.id = 456
    interaction.channel.create_thread = AsyncMock()

    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 789

    interaction.command = MagicMock(spec=app_commands.Command)
    interaction.command.name = "waitlist"

    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock(send=AsyncMock())

    return interaction


@pytest.fixture
def mock_event_obj(sample_event_list):
    """Fixture providing a specific Event object (e.g., Summer Bash)."""
    return next(e for e in sample_event_list if e.event_name == "Summer Bash")


# --- Test Cases ---


@patch("offkai_bot.cogs.events.calculate_waitlist")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_waitlist_success(
    mock_log,
    mock_get_event,
    mock_calculate_waitlist,
    mock_interaction,
    mock_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test the successful path of waitlist."""
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj

    mock_total_count = 3
    mock_waitlisted_list = ["UserA", "UserA +1", "UserB"]
    mock_calculate_waitlist.return_value = (mock_total_count, mock_waitlisted_list)

    await EventsCog.waitlist.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_target,
    )

    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_waitlist.assert_called_once_with(event_name_target, nicknames=False)

    expected_output = (
        f"**Waitlist for {event_name_target}**\n\n"
        f"Total Waitlisted: **{mock_total_count}**\n\n"
        "1. UserA\n"
        "2. UserA +1\n"
        "3. UserB"
    )
    mock_interaction.response.send_message.assert_awaited_once_with(expected_output, ephemeral=True)
    mock_log.warning.assert_not_called()


@patch("offkai_bot.cogs.events.calculate_waitlist")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_waitlist_sort_success(
    mock_log,
    mock_get_event,
    mock_calculate_waitlist,
    mock_interaction,
    mock_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test the successful path of waitlist with sorting."""
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj

    mock_total_count = 3
    mock_waitlisted_list = ["UserC", "UserA", "UserB"]
    mock_calculate_waitlist.return_value = (mock_total_count, mock_waitlisted_list)

    await EventsCog.waitlist.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_target,
        sort=True,
    )

    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_waitlist.assert_called_once_with(event_name_target, nicknames=False)

    expected_output = (
        f"**Waitlist for {event_name_target}**\n\n"
        f"Total Waitlisted: **{mock_total_count}**\n\n"
        "1. UserA\n"
        "2. UserB\n"
        "3. UserC"
    )
    mock_interaction.response.send_message.assert_awaited_once_with(expected_output, ephemeral=True)
    mock_log.warning.assert_not_called()


@patch("offkai_bot.cogs.events.calculate_waitlist")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_waitlist_success_truncation(
    mock_log,
    mock_get_event,
    mock_calculate_waitlist,
    mock_interaction,
    mock_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test waitlist output truncation when the list is very long."""
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj

    long_waitlisted_list = [f"User{i:03d}" for i in range(1000)]
    mock_total_count = 100
    mock_calculate_waitlist.return_value = (mock_total_count, long_waitlisted_list)

    full_output_list = "\n".join(f"{i + 1}. {name}" for i, name in enumerate(long_waitlisted_list))
    full_output = (
        f"**Waitlist for {event_name_target}**\n\nTotal Waitlisted: **{mock_total_count}**\n\n{full_output_list}"
    )
    assert len(full_output) > 1900

    expected_truncated_output = full_output[:1900] + "\n... (list truncated)"

    await EventsCog.waitlist.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_target,
    )

    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_waitlist.assert_called_once_with(event_name_target, nicknames=False)
    mock_interaction.response.send_message.assert_awaited_once_with(expected_truncated_output, ephemeral=True)


@patch("offkai_bot.cogs.events.calculate_waitlist")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_waitlist_event_not_found(
    mock_log,
    mock_get_event,
    mock_calculate_waitlist,
    mock_interaction,
    prepopulated_event_cache,
    mock_cog,
):
    """Test waitlist when the initial get_event fails."""
    event_name_target = "NonExistent Event"
    mock_get_event.side_effect = EventNotFoundError(event_name_target)

    with pytest.raises(EventNotFoundError):
        await EventsCog.waitlist.callback(
            mock_cog,
            mock_interaction,
            event_name=event_name_target,
        )

    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_waitlist.assert_not_called()
    mock_interaction.response.send_message.assert_not_awaited()


@patch("offkai_bot.cogs.events.calculate_waitlist")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_waitlist_no_entries_found(
    mock_log,
    mock_get_event,
    mock_calculate_waitlist,
    mock_interaction,
    mock_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test waitlist when calculate_waitlist raises NoWaitlistEntriesFoundError."""
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj
    mock_calculate_waitlist.side_effect = NoWaitlistEntriesFoundError(event_name_target)

    with pytest.raises(NoWaitlistEntriesFoundError):
        await EventsCog.waitlist.callback(
            mock_cog,
            mock_interaction,
            event_name=event_name_target,
        )

    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_waitlist.assert_called_once_with(event_name_target, nicknames=False)
    mock_interaction.response.send_message.assert_not_awaited()


@patch("offkai_bot.cogs.events.calculate_waitlist")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_waitlist_with_nicknames(
    mock_log,
    mock_get_event,
    mock_calculate_waitlist,
    mock_interaction,
    mock_event_obj,
    prepopulated_event_cache,
    mock_cog,
):
    """Test that nicknames=True is passed through to calculate_waitlist."""
    event_name_target = "Summer Bash"
    mock_get_event.return_value = mock_event_obj
    mock_calculate_waitlist.return_value = (2, ["foo (goo)", "bar"])

    await EventsCog.waitlist.callback(
        mock_cog,
        mock_interaction,
        event_name=event_name_target,
        nicknames=True,
    )

    mock_get_event.assert_called_once_with(event_name_target)
    mock_calculate_waitlist.assert_called_once_with(event_name_target, nicknames=True)

    expected_output = f"**Waitlist for {event_name_target}**\n\nTotal Waitlisted: **2**\n\n1. foo (goo)\n2. bar"
    mock_interaction.response.send_message.assert_awaited_once_with(expected_output, ephemeral=True)
