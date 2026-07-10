# tests/commands/test_create_interest_check.py

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands
from offkai_bot.cogs.events import EventsCog
from offkai_bot.data.event import Event
from offkai_bot.errors import (
    DuplicateEventError,
    EventNotFoundError,
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
    interaction.command.name = "create_interest_check"

    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock(return_value=MagicMock(spec=discord.Message))

    return interaction


@pytest.fixture
def mock_thread():
    """Fixture for a mock discord.Thread."""
    thread = MagicMock(spec=discord.Thread)
    thread.id = 111222333
    thread.mention = "<#111222333>"
    thread.send = AsyncMock()
    return thread


@pytest.fixture
def mock_created_interest_event():
    """Fixture for the Event object returned by add_event."""
    now = datetime.now(UTC)
    event_dt = now + timedelta(days=30)
    deadline_dt = event_dt - timedelta(days=7)
    return Event(
        event_name="Test Interest Check",
        venue="TBD",
        address="TBD",
        google_maps_link="",
        event_datetime=event_dt,
        event_deadline=deadline_dt,
        channel_id=456,
        thread_id=111222333,
        message_id=None,
        open=True,
        archived=False,
        drinks=[],
        message="Announce",
        max_capacity=None,
        interest_check=True,
    )


# --- Test Cases ---


@patch("offkai_bot.cogs.events.send_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.register_checkin_reminder")
@patch("offkai_bot.cogs.events.register_deadline_reminders")
@patch("offkai_bot.cogs.events.add_event")
@patch("offkai_bot.cogs.events.validate_interaction_context")
@patch("offkai_bot.cogs.events.parse_event_datetime")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events._log")
async def test_create_interest_check_success(
    mock_log,
    mock_get_event,
    mock_parse_dt,
    mock_validate_ctx,
    mock_add_event,
    mock_register_reminders,
    mock_register_checkin,
    mock_send_event_message,
    mock_interaction,
    mock_thread,
    mock_created_interest_event,
    mock_cog,
):
    """Interest check creation stores placeholders, sets the flag, and skips check-in reminders."""
    # Arrange
    event = mock_created_interest_event
    mock_get_event.side_effect = EventNotFoundError(event.event_name)
    mock_parse_dt.side_effect = [event.event_datetime, event.event_deadline]
    mock_interaction.channel.create_thread.return_value = mock_thread
    mock_add_event.return_value = event

    # Act
    await EventsCog.create_interest_check.callback(
        mock_cog,
        mock_interaction,
        event_name=event.event_name,
        date_time="2030-08-15 19:30",
        deadline="2030-08-08 19:30",
        announce_msg="Announce",
    )

    # Assert
    mock_add_event.assert_called_once_with(
        event_name=event.event_name,
        venue="TBD",
        address="TBD",
        google_maps_link="",
        event_datetime=event.event_datetime,
        event_deadline=event.event_deadline,
        channel_id=mock_interaction.channel.id,
        thread_id=mock_thread.id,
        drinks_list=[],
        announce_msg="Announce",
        max_capacity=None,
        creator_id=mock_interaction.user.id,
        interest_check=True,
    )
    mock_register_reminders.assert_called_once_with(mock_cog.bot, event, mock_thread)
    # Interest checks never send QR/check-in DMs.
    mock_register_checkin.assert_not_called()
    mock_send_event_message.assert_awaited_once_with(mock_thread, event)

    # Announcement posted and pinned.
    mock_interaction.followup.send.assert_awaited_once()
    announce_text = mock_interaction.followup.send.call_args[0][0]
    assert announce_text.startswith("# Interest Check: ")
    assert mock_thread.mention in announce_text
    mock_interaction.followup.send.return_value.pin.assert_awaited_once()


@patch("offkai_bot.cogs.events.parse_event_datetime")
@patch("offkai_bot.cogs.events.get_event")
async def test_create_interest_check_duplicate_name(
    mock_get_event,
    mock_parse_dt,
    mock_interaction,
    mock_created_interest_event,
    mock_cog,
):
    """A pre-existing event with the same name is rejected."""
    mock_get_event.return_value = mock_created_interest_event

    with pytest.raises(DuplicateEventError):
        await EventsCog.create_interest_check.callback(
            mock_cog,
            mock_interaction,
            event_name=mock_created_interest_event.event_name,
            date_time="2030-08-15 19:30",
        )

    mock_interaction.channel.create_thread.assert_not_called()
