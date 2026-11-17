# tests/commands/test_broadcast_dm.py

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from offkai_bot.cogs.events import (
    BROADCAST_DM_ALL,
    BROADCAST_DM_ATTENDEES,
    BROADCAST_DM_MAX_LENGTH,
    EventsCog,
)
from offkai_bot.data import event as event_data
from offkai_bot.data import response as response_data
from offkai_bot.data.event import Event
from offkai_bot.data.response import EventData, Response, WaitlistEntry
from offkai_bot.errors import BroadcastMessageTooLongError, EventNotFoundError
from offkai_bot.event_actions import build_participant_dm, dm_event_participants, get_dm_recipients

pytestmark = pytest.mark.asyncio

EVENT_NAME = "Summer Bash"
NOW = datetime(2026, 11, 1, tzinfo=UTC)


def _response(user_id: int, username: str, display_name: str | None = None) -> Response:
    return Response(user_id, username, 0, True, True, EVENT_NAME, NOW, display_name=display_name)


def _waitlist(user_id: int, username: str) -> WaitlistEntry:
    return WaitlistEntry(user_id, username, 0, True, True, EVENT_NAME, NOW)


@pytest.fixture
def event() -> Event:
    return Event(EVENT_NAME, "Venue", "Address", "Maps", NOW, channel_id=10, open=True)


@pytest.fixture
def populated(event):
    event_data.EVENT_DATA_CACHE = [event]
    response_data.RESPONSE_DATA_CACHE = {
        EVENT_NAME: EventData(
            attendees=[_response(1, "alice", "Alice"), _response(2, "bob")],
            waitlist=[_waitlist(3, "carol"), _waitlist(1, "alice")],
        )
    }
    return event


@pytest.fixture(autouse=True)
def no_throttle():
    with patch("offkai_bot.event_actions.asyncio.sleep", new_callable=AsyncMock) as sleep:
        yield sleep


def _make_client(failing: dict[int, Exception] | None = None) -> tuple[MagicMock, dict[int, MagicMock]]:
    """A client whose get_user misses the cache, so fetch_user yields per-id mock users."""
    failing = failing or {}
    users: dict[int, MagicMock] = {}

    async def fetch_user(user_id: int) -> MagicMock:
        if user_id in failing:
            raise failing[user_id]
        users[user_id] = MagicMock(send=AsyncMock())
        return users[user_id]

    client = MagicMock(spec=commands.Bot)
    client.get_user.return_value = None
    client.fetch_user = AsyncMock(side_effect=fetch_user)
    return client, users


def _forbidden() -> discord.Forbidden:
    return discord.Forbidden(MagicMock(status=403), "Cannot send messages to this user")


@pytest.fixture
def interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 123
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 789
    interaction.guild.get_channel_or_thread.side_effect = lambda cid: object() if cid == 10 else None
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.command = MagicMock(spec=app_commands.Command)
    interaction.command.name = "broadcast"
    interaction.response = MagicMock(defer=AsyncMock(), send_message=AsyncMock())
    interaction.followup = MagicMock(send=AsyncMock())
    return interaction


# --- get_dm_recipients ---


async def test_recipients_default_to_attendees_only(populated):
    assert [r.user_id for r in get_dm_recipients(EVENT_NAME)] == [1, 2]


async def test_recipients_include_waitlist_deduplicated(populated):
    assert [r.user_id for r in get_dm_recipients(EVENT_NAME, include_waitlist=True)] == [1, 2, 3]


# --- dm_event_participants ---


async def test_dm_sends_wrapped_message_without_mentions(populated, no_throttle):
    client, users = _make_client()

    result = await dm_event_participants(client, populated, "@everyone meet at 6pm")

    expected = build_participant_dm(populated, "@everyone meet at 6pm")
    assert EVENT_NAME in expected and expected.endswith("@everyone meet at 6pm")
    assert set(users) == {1, 2}
    for user in users.values():
        user.send.assert_awaited_once()
        assert user.send.await_args.args == (expected,)
        allowed = user.send.await_args.kwargs["allowed_mentions"]
        assert allowed.to_dict() == discord.AllowedMentions.none().to_dict()
    assert result.sent == ["Alice (@alice)", "bob"]
    assert result.failed == []
    # Throttled between sends only, never after the last one.
    assert no_throttle.await_count == 1


async def test_dm_continues_past_failures(populated):
    client, users = _make_client(failing={1: _forbidden(), 3: discord.NotFound(MagicMock(status=404), "Unknown User")})

    result = await dm_event_participants(client, populated, "hi", include_waitlist=True)

    assert set(users) == {2}
    assert result.sent == ["bob"]
    assert result.failed == ["Alice (@alice)", "carol"]
    assert result.total == 3


async def test_dm_uses_cached_user_when_available(populated):
    client, _ = _make_client()
    cached = MagicMock(send=AsyncMock())
    client.get_user.return_value = cached

    result = await dm_event_participants(client, populated, "hi")

    client.fetch_user.assert_not_awaited()
    assert cached.send.await_count == 2
    assert len(result.sent) == 2


async def test_dm_send_failure_is_reported(populated):
    client, _ = _make_client()
    broken = MagicMock(send=AsyncMock(side_effect=_forbidden()))
    client.get_user.side_effect = lambda uid: broken if uid == 2 else None

    result = await dm_event_participants(client, populated, "hi")

    assert result.sent == ["Alice (@alice)"]
    assert result.failed == ["bob"]


# --- /broadcast with a DM destination ---

DM_ATTENDEES = app_commands.Choice(name="DM attendees", value=BROADCAST_DM_ATTENDEES)
DM_ALL = app_commands.Choice(name="DM attendees + waitlist", value=BROADCAST_DM_ALL)


async def test_broadcast_dm_reports_success(populated, interaction):
    client, users = _make_client()
    cog = EventsCog(client)

    with patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock) as fetch_thread:
        await EventsCog.broadcast.callback(
            cog, interaction, event_name=EVENT_NAME, message="See you there!", destination=DM_ATTENDEES
        )

    fetch_thread.assert_not_awaited()  # DM destinations never post in the thread
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    assert set(users) == {1, 2}
    interaction.followup.send.assert_awaited_once()
    text = interaction.followup.send.await_args.args[0]
    assert "**2** of 2" in text
    assert "Could not DM" not in text
    assert interaction.followup.send.await_args.kwargs["ephemeral"] is True


async def test_broadcast_dm_all_includes_waitlist_and_lists_failures(populated, interaction):
    client, users = _make_client(failing={2: _forbidden()})
    cog = EventsCog(client)

    await EventsCog.broadcast.callback(cog, interaction, event_name=EVENT_NAME, message="hi", destination=DM_ALL)

    assert set(users) == {1, 3}
    text = interaction.followup.send.await_args.args[0]
    assert "**2** of 3" in text
    assert "Could not DM" in text and "- bob" in text


async def test_broadcast_dm_with_no_recipients(event, interaction):
    event_data.EVENT_DATA_CACHE = [event]
    response_data.RESPONSE_DATA_CACHE = {EVENT_NAME: EventData(attendees=[], waitlist=[_waitlist(3, "carol")])}
    client, users = _make_client()
    cog = EventsCog(client)

    await EventsCog.broadcast.callback(cog, interaction, event_name=EVENT_NAME, message="hi", destination=DM_ATTENDEES)

    assert users == {}
    interaction.followup.send.assert_awaited_once_with(f"ℹ️ '{EVENT_NAME}' has no attendees to message.", ephemeral=True)


async def test_broadcast_dm_rejects_overlong_message(populated, interaction):
    client, users = _make_client()
    cog = EventsCog(client)

    with pytest.raises(BroadcastMessageTooLongError):
        await EventsCog.broadcast.callback(
            cog,
            interaction,
            event_name=EVENT_NAME,
            message="x" * (BROADCAST_DM_MAX_LENGTH + 1),
            destination=DM_ATTENDEES,
        )

    assert users == {}


async def test_broadcast_dm_event_not_found(populated, interaction):
    client, users = _make_client()
    cog = EventsCog(client)

    with pytest.raises(EventNotFoundError):
        await EventsCog.broadcast.callback(cog, interaction, event_name="Nope", message="hi", destination=DM_ATTENDEES)

    assert users == {}
    interaction.followup.send.assert_not_awaited()
