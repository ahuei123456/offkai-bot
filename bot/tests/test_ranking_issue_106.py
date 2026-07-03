# tests/test_ranking_issue_106.py
"""Regression tests for issue #106: rank updates must not depend on DM success,
rankings are keyed by user ID, and every withdrawal path decrements rank."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands
from offkai_bot.cogs.events import EventsCog
from offkai_bot.data.event import Event
from offkai_bot.data.response import Response
from offkai_bot.interactions import ClosedEvent, GatheringModal, OpenEvent, PostDeadlineEvent

pytestmark = pytest.mark.asyncio

# --- Fixtures ---


@pytest.fixture
def open_event():
    """An open event with no capacity limit."""
    now = datetime.now(UTC)
    return Event(
        event_name="Ranking Test Event",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=now + timedelta(days=30),
        event_deadline=now + timedelta(days=7),
        channel_id=456,
        thread_id=111,
        message_id=None,
        open=True,
        archived=False,
        drinks=[],
        max_capacity=None,
    )


@pytest.fixture
def mock_interaction():
    """Mock discord.Interaction for modal/button callbacks."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 123
    interaction.user.name = "TestUser"
    interaction.user.send = AsyncMock()
    interaction.guild = None
    interaction.channel = MagicMock(spec=discord.Thread)
    interaction.channel.id = 456
    interaction.channel.send = AsyncMock()
    interaction.channel.add_user = AsyncMock()
    interaction.channel.remove_user = AsyncMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.client = MagicMock()
    interaction.client.fetch_user = AsyncMock()
    return interaction


@pytest.fixture
def sample_response(open_event):
    return Response(
        user_id=123,
        username="TestUser",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=open_event.event_name,
        timestamp=datetime.now(UTC),
        drinks=[],
    )


# --- Rank update must not depend on DM success ---


async def test_rank_updates_when_dm_fails(open_event, mock_interaction, sample_response):
    """Users with DMs closed must still accrue rank (defect 1)."""
    mock_interaction.user.send.side_effect = discord.Forbidden(MagicMock(), "DMs closed")
    modal = GatheringModal(event=open_event)

    with (
        patch("offkai_bot.interactions.update_rank") as mock_update,
        patch("offkai_bot.interactions.get_rank", return_value=2) as mock_get,
        patch("offkai_bot.interactions.can_rank_message_sent", return_value=False),
        patch("offkai_bot.interactions.mark_achieved_rank"),
    ):
        await modal._handle_successful_submission(mock_interaction, sample_response)

    mock_update.assert_called_once_with(123, "TestUser")
    mock_get.assert_called_once_with(123, "TestUser")
    # The fallback ephemeral confirmation was still sent
    mock_interaction.response.send_message.assert_awaited_once()


async def test_milestone_announced_when_dm_fails(open_event, mock_interaction, sample_response):
    """Milestone shout-outs must also fire when the DM fails."""
    mock_interaction.user.send.side_effect = discord.Forbidden(MagicMock(), "DMs closed")
    modal = GatheringModal(event=open_event)

    with (
        patch("offkai_bot.interactions.update_rank"),
        patch("offkai_bot.interactions.get_rank", return_value=1),
        patch("offkai_bot.interactions.can_rank_message_sent", return_value=True),
        patch("offkai_bot.interactions.mark_achieved_rank") as mock_mark,
    ):
        await modal._handle_successful_submission(mock_interaction, sample_response)

    mock_interaction.channel.send.assert_awaited_once()
    mock_mark.assert_called_once_with(123)


async def test_rank_updates_when_channel_not_messageable(open_event, mock_interaction, sample_response):
    """Rank accrues even without a messageable channel; only the announcement is skipped."""
    mock_interaction.channel = None
    modal = GatheringModal(event=open_event)

    with (
        patch("offkai_bot.interactions.update_rank") as mock_update,
        patch("offkai_bot.interactions.get_rank", return_value=1),
        patch("offkai_bot.interactions.can_rank_message_sent", return_value=True),
        patch("offkai_bot.interactions.mark_achieved_rank") as mock_mark,
    ):
        await modal._handle_successful_submission(mock_interaction, sample_response)

    mock_update.assert_called_once_with(123, "TestUser")
    mock_mark.assert_not_called()


async def test_milestone_send_failure_does_not_mark_achieved(open_event, mock_interaction, sample_response):
    """If the milestone announcement fails to send, the achievement stays unmarked for a retry."""
    mock_interaction.channel.send.side_effect = discord.HTTPException(MagicMock(), "send failed")
    modal = GatheringModal(event=open_event)

    with (
        patch("offkai_bot.interactions.update_rank") as mock_update,
        patch("offkai_bot.interactions.get_rank", return_value=1),
        patch("offkai_bot.interactions.can_rank_message_sent", return_value=True),
        patch("offkai_bot.interactions.mark_achieved_rank") as mock_mark,
    ):
        await modal._handle_successful_submission(mock_interaction, sample_response)

    mock_update.assert_called_once_with(123, "TestUser")
    mock_mark.assert_not_called()


# --- All withdrawal paths must decrement rank (defect 3) ---


@pytest.mark.parametrize("view_cls", [OpenEvent, ClosedEvent, PostDeadlineEvent])
async def test_withdraw_decrements_rank(view_cls, open_event, mock_interaction):
    """Withdrawing a confirmed response decrements rank in every event view."""
    view = view_cls(open_event)

    with (
        patch("offkai_bot.interactions.remove_response") as mock_remove,
        patch("offkai_bot.interactions.decrease_rank") as mock_decrease,
        patch("offkai_bot.interactions.promote_waitlist_batch", new_callable=AsyncMock),
    ):
        await view.withdraw.callback(mock_interaction)

    mock_remove.assert_called_once_with(open_event.event_name, 123)
    mock_decrease.assert_called_once_with(123, "TestUser")


@pytest.mark.parametrize("view_cls", [OpenEvent, ClosedEvent, PostDeadlineEvent])
async def test_withdraw_from_waitlist_does_not_decrement_rank(view_cls, open_event, mock_interaction):
    """Leaving the waitlist never earned rank credit, so it must not decrement."""
    from offkai_bot.errors import ResponseNotFoundError

    view = view_cls(open_event)

    with (
        patch(
            "offkai_bot.interactions.remove_response",
            side_effect=ResponseNotFoundError(open_event.event_name, 123),
        ),
        patch("offkai_bot.interactions.remove_from_waitlist"),
        patch("offkai_bot.interactions.decrease_rank") as mock_decrease,
        patch("offkai_bot.interactions.promote_waitlist_batch", new_callable=AsyncMock),
    ):
        await view.withdraw.callback(mock_interaction)

    mock_decrease.assert_not_called()


async def test_delete_response_decrements_rank(mock_interaction, prepopulated_event_cache):
    """Organizer /delete_response also removes the rank credit."""
    bot = MagicMock(spec=commands.Bot)
    cog = EventsCog(bot)

    member = MagicMock(spec=discord.Member)
    member.id = 98765
    member.name = "TargetUser"
    member.mention = "<@98765>"

    mock_interaction.response.defer = AsyncMock()
    mock_interaction.followup = MagicMock(send=AsyncMock())

    with (
        patch("offkai_bot.cogs.events.get_event") as mock_get_event,
        patch("offkai_bot.cogs.events.remove_response") as mock_remove,
        patch("offkai_bot.cogs.events.decrease_rank") as mock_decrease,
    ):
        mock_get_event.return_value = prepopulated_event_cache[0]
        cog.bot.get_channel.return_value = None

        await EventsCog.delete_response.callback(
            cog,
            mock_interaction,
            event_name=prepopulated_event_cache[0].event_name,
            member=member,
        )

    mock_remove.assert_called_once_with(prepopulated_event_cache[0].event_name, 98765)
    mock_decrease.assert_called_once_with(98765, "TargetUser")
