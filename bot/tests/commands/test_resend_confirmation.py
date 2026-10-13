# tests/commands/test_resend_confirmation.py

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from offkai_bot.cogs.events import EventsCog
from offkai_bot.data import event as event_data
from offkai_bot.data import response as response_data
from offkai_bot.data.event import Event
from offkai_bot.data.response import EventData, Response, WaitlistEntry
from offkai_bot.errors import InterestCheckOperationError, ResponseNotFoundError

TS = datetime(2026, 10, 10, 1, 0, tzinfo=UTC)
EVENT_NAME = "Resend Event"


def make_event(**overrides) -> Event:
    fields = dict(
        event_name=EVENT_NAME,
        venue="Venue",
        address="Address",
        google_maps_link="",
        event_datetime=datetime.now(UTC) + timedelta(days=7),
        open=False,
    )
    fields.update(overrides)
    return Event(**fields)


def make_entry(cls, user_id, username, display_name, guests=()):
    return cls(
        user_id=user_id,
        username=username,
        extra_people=len(guests),
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=EVENT_NAME,
        timestamp=TS,
        extras_names=list(guests),
        display_name=display_name,
        payment_method="PayNow",
        no_show_agreed=True,
    )


@pytest.fixture
def setup_data(mock_paths):
    response_data.RESPONSE_DATA_CACHE = {
        EVENT_NAME: EventData(
            attendees=[
                make_entry(Response, 1, "alice", "Alice", ["Guest A"]),
                make_entry(Response, 2, "bob", "Bob"),
            ],
            waitlist=[make_entry(WaitlistEntry, 3, "carol", "Carol")],
        )
    }


@pytest.fixture
def users():
    """Discord users the bot can fetch, keyed by id, each with a mock DM channel."""
    return {uid: MagicMock(spec=discord.User, id=uid, send=AsyncMock()) for uid in (1, 2, 3)}


@pytest.fixture
def cog(users):
    bot = MagicMock(spec=commands.Bot)
    bot.fetch_user = AsyncMock(side_effect=lambda uid: users[uid])
    return EventsCog(bot)


@pytest.fixture
def interaction():
    value = MagicMock(spec=discord.Interaction)
    value.user = MagicMock(spec=discord.Member, id=999)
    value.guild = MagicMock(spec=discord.Guild)
    value.channel = MagicMock(spec=discord.TextChannel)
    value.response = MagicMock(defer=AsyncMock())
    value.followup = MagicMock(send=AsyncMock())
    return value


def dm_text(user) -> str:
    call = user.send.call_args
    if call.args:
        return call.args[0]
    return "\n\n".join(embed.description for embed in call.kwargs["embeds"])


async def test_resends_current_details_to_attendees_and_waitlist(cog, interaction, users, setup_data):
    event_data.EVENT_DATA_CACHE = [make_event()]
    with patch("offkai_bot.interactions.build_checkin_url", return_value=None):
        await EventsCog.resend_confirmation.callback(cog, interaction, EVENT_NAME)

    alice, carol = dm_text(users[1]), dm_text(users[3])
    assert "organizers updated your registration" in alice and "主催者が" in alice
    assert "Name recorded: Alice" in alice and "Bringing: 1 extra guest(s)" in alice
    assert "Attendance confirmed" in alice
    assert "waitlist" in carol and "Name recorded: Carol" in carol
    users[2].send.assert_awaited_once()
    assert "to 3 registrant(s)" in interaction.followup.send.call_args.args[0]


async def test_custom_form_event_resends_custom_reply_with_notice(cog, interaction, users, setup_data):
    event_data.EVENT_DATA_CACHE = [
        make_event(signup_form={"fields": ["preferred_name", "guests"], "payment_methods": {"PayNow": "Pay here"}})
    ]
    with patch("offkai_bot.interactions.build_checkin_url", return_value=None):
        await EventsCog.resend_confirmation.callback(cog, interaction, EVENT_NAME)

    alice = dm_text(users[1])
    assert alice.startswith("🔄 The organizers updated your registration")
    assert "(Guest A)" in alice and "Payment method: PayNow" in alice and "Pay here" in alice


async def test_member_option_only_dms_that_member(cog, interaction, users, setup_data):
    event_data.EVENT_DATA_CACHE = [make_event()]
    member = MagicMock(spec=discord.Member, id=2)
    with patch("offkai_bot.interactions.build_checkin_url", return_value=None):
        await EventsCog.resend_confirmation.callback(cog, interaction, EVENT_NAME, member)

    users[2].send.assert_awaited_once()
    users[1].send.assert_not_awaited()
    users[3].send.assert_not_awaited()


async def test_unregistered_member_is_rejected(cog, interaction, users, setup_data):
    event_data.EVENT_DATA_CACHE = [make_event()]
    with pytest.raises(ResponseNotFoundError):
        await EventsCog.resend_confirmation.callback(
            cog, interaction, EVENT_NAME, MagicMock(spec=discord.Member, id=42)
        )
    for user in users.values():
        user.send.assert_not_awaited()


async def test_dm_failures_are_reported_and_do_not_stop_others(cog, interaction, users, setup_data):
    event_data.EVENT_DATA_CACHE = [make_event()]
    users[1].send.side_effect = discord.Forbidden(MagicMock(status=403), "DMs closed")
    with patch("offkai_bot.interactions.build_checkin_url", return_value=None):
        await EventsCog.resend_confirmation.callback(cog, interaction, EVENT_NAME)

    users[2].send.assert_awaited_once()
    users[3].send.assert_awaited_once()
    reply = interaction.followup.send.call_args.args[0]
    assert "to 2 registrant(s)" in reply and "Couldn't DM 1" in reply and "alice" in reply


async def test_interest_checks_are_rejected(cog, interaction, setup_data):
    event_data.EVENT_DATA_CACHE = [make_event(interest_check=True)]
    with pytest.raises(InterestCheckOperationError):
        await EventsCog.resend_confirmation.callback(cog, interaction, EVENT_NAME)
