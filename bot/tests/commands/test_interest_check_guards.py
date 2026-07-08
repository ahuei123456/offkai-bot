# tests/commands/test_interest_check_guards.py
"""Full-signup commands must refuse (or degrade gracefully for) interest-check events."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands
from offkai_bot.cogs.events import EventsCog
from offkai_bot.data.event import Event
from offkai_bot.errors import InterestCheckOperationError

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

    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 789

    interaction.command = MagicMock(spec=app_commands.Command)
    interaction.command.name = "test_command"

    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock(send=AsyncMock())

    return interaction


@pytest.fixture
def interest_event():
    now = datetime.now(UTC)
    return Event(
        event_name="Interest Test",
        venue="TBD",
        address="TBD",
        google_maps_link="",
        event_datetime=now + timedelta(days=30),
        event_deadline=now + timedelta(days=7),
        channel_id=456,
        thread_id=789,
        message_id=None,
        open=True,
        archived=False,
        drinks=[],
        max_capacity=None,
        interest_check=True,
    )


# --- Guard Tests ---


@patch("offkai_bot.cogs.events.get_event")
async def test_promote_rejected_for_interest_check(mock_get_event, mock_interaction, interest_event, mock_cog):
    mock_get_event.return_value = interest_event

    with pytest.raises(InterestCheckOperationError):
        await EventsCog.promote.callback(
            mock_cog, mock_interaction, event_name=interest_event.event_name, username="98765"
        )


@patch("offkai_bot.cogs.events.calculate_waitlist")
@patch("offkai_bot.cogs.events.get_event")
async def test_waitlist_rejected_for_interest_check(
    mock_get_event, mock_calculate_waitlist, mock_interaction, interest_event, mock_cog
):
    mock_get_event.return_value = interest_event

    with pytest.raises(InterestCheckOperationError):
        await EventsCog.waitlist.callback(mock_cog, mock_interaction, event_name=interest_event.event_name)

    mock_calculate_waitlist.assert_not_called()


@patch("offkai_bot.cogs.events.calculate_drinks")
@patch("offkai_bot.cogs.events.get_event")
async def test_drinks_rejected_for_interest_check(
    mock_get_event, mock_calculate_drinks, mock_interaction, interest_event, mock_cog
):
    mock_get_event.return_value = interest_event

    with pytest.raises(InterestCheckOperationError):
        await EventsCog.drinks.callback(mock_cog, mock_interaction, event_name=interest_event.event_name)

    mock_calculate_drinks.assert_not_called()


@patch("offkai_bot.cogs.events.update_event_details")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events.validate_interaction_context")
async def test_modify_rejects_capacity_for_interest_check(
    mock_validate_ctx, mock_get_event, mock_update_details, mock_interaction, interest_event, mock_cog
):
    mock_get_event.return_value = interest_event

    with pytest.raises(InterestCheckOperationError):
        await EventsCog.modify_offkai.callback(
            mock_cog,
            mock_interaction,
            event_name=interest_event.event_name,
            update_msg="update",
            max_capacity=20,
        )

    mock_update_details.assert_not_called()


@patch("offkai_bot.cogs.events.update_event_details")
@patch("offkai_bot.cogs.events.get_event")
@patch("offkai_bot.cogs.events.validate_interaction_context")
async def test_modify_rejects_drinks_for_interest_check(
    mock_validate_ctx, mock_get_event, mock_update_details, mock_interaction, interest_event, mock_cog
):
    mock_get_event.return_value = interest_event

    with pytest.raises(InterestCheckOperationError):
        await EventsCog.modify_offkai.callback(
            mock_cog,
            mock_interaction,
            event_name=interest_event.event_name,
            update_msg="update",
            drinks="Beer, Wine",
        )

    mock_update_details.assert_not_called()


@patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.promote_waitlist_batch", new_callable=AsyncMock)
@patch("offkai_bot.cogs.events.decrease_rank")
@patch("offkai_bot.cogs.events.remove_response")
@patch("offkai_bot.cogs.events.get_event")
async def test_delete_response_interest_check_skips_rank_and_promotion(
    mock_get_event,
    mock_remove_response,
    mock_decrease_rank,
    mock_promote,
    mock_update_message,
    mock_interaction,
    interest_event,
    mock_cog,
):
    mock_get_event.return_value = interest_event
    mock_remove_response.return_value = MagicMock(extra_people=1)
    member = MagicMock(spec=discord.Member)
    member.id = 98765
    member.mention = "<@98765>"
    mock_cog.bot.get_channel.return_value = MagicMock(spec=discord.Thread, remove_user=AsyncMock())

    await EventsCog.delete_response.callback(
        mock_cog, mock_interaction, event_name=interest_event.event_name, member=member
    )

    mock_remove_response.assert_called_once_with(interest_event.event_name, member.id)
    mock_decrease_rank.assert_not_called()
    mock_promote.assert_not_awaited()
    # The live interested count on the announcement is refreshed.
    mock_update_message.assert_awaited_once_with(mock_cog.bot, interest_event)
    mock_interaction.followup.send.assert_awaited_once()
