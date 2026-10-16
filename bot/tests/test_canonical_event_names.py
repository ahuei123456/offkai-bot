"""Case-insensitive event lookup must retain canonical response-storage keys."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from aiohttp.test_utils import TestClient, TestServer
from discord.ext import commands

from offkai_bot import admin_api
from offkai_bot.cogs.events import EventsCog
from offkai_bot.data import event as event_data
from offkai_bot.data import response as response_data
from offkai_bot.data.event import Event, update_event_details
from offkai_bot.data.response import EventData, Response, WaitlistEntry
from offkai_bot.data.responses_transfer import export_responses_json
from offkai_bot.errors import CapacityReductionError, CapacityReductionWithWaitlistError, ResponsesImportError
from offkai_bot.event_actions import perform_close_event


@pytest.fixture
def stored_event():
    event = Event(
        "Summer Bash",
        "Venue",
        "Address",
        "",
        datetime.now(UTC) + timedelta(days=7),
        open=True,
        max_capacity=10,
        channel_id=1001,
        drinks=["Tea"],
    )
    attendee = Response(
        123000000000000001,
        "Alice",
        1,
        True,
        True,
        event.event_name,
        datetime.now(UTC),
        extras_names=["Guest"],
        drinks=["Tea", "Tea"],
    )
    queued = WaitlistEntry(456, "Bob", 0, True, True, event.event_name, datetime.now(UTC))
    event_data.EVENT_DATA_CACHE = [event]
    response_data.RESPONSE_DATA_CACHE = {event.event_name: EventData(attendees=[attendee], waitlist=[queued])}
    return event, attendee, queued


def interaction():
    value = MagicMock(spec=discord.Interaction)
    value.guild = MagicMock(spec=discord.Guild)
    value.channel = MagicMock(spec=discord.TextChannel)
    value.response = MagicMock(defer=AsyncMock(), send_message=AsyncMock())
    value.followup = MagicMock(send=AsyncMock())
    value.user = MagicMock(send=AsyncMock())
    return value


async def test_mixed_case_close_records_real_attendance_and_numbers_then_reopen_clears(stored_event):
    event, attendee, _ = stored_event
    bot = MagicMock(spec=commands.Bot)
    with patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock):
        await perform_close_event(bot, "summer bash")
    assert event.closed_attendance_count == 2
    assert event.max_attendee_number == 2
    assert attendee.attendee_number == 1 and attendee.extras_attendee_numbers == [2]
    assert set(response_data.load_responses()) == {"Summer Bash"}
    with patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock):
        await EventsCog.reopen_offkai.callback(EventsCog(bot), interaction(), "SUMMER BASH")
    assert attendee.attendee_number is None and attendee.extras_attendee_numbers == []
    assert set(response_data.load_responses()) == {"Summer Bash"}


@pytest.mark.parametrize("capacity,error", [(1, CapacityReductionError), (3, CapacityReductionWithWaitlistError)])
def test_mixed_case_capacity_reduction_checks_existing_roster(stored_event, capacity, error):
    event, _, _ = stored_event
    with pytest.raises(error):
        update_event_details("sUMMER bASH", max_capacity=capacity)
    assert event.max_capacity == 10


@pytest.mark.parametrize("command,expected", [("attendance", "Alice"), ("waitlist", "Bob"), ("drinks", "Tea: 2")])
async def test_mixed_case_organizer_reports_read_real_roster(stored_event, command, expected):
    source = interaction()
    await getattr(EventsCog, command).callback(EventsCog(MagicMock(spec=commands.Bot)), source, "summer bash")
    sent = source.followup.send
    assert expected in sent.call_args.args[0]


async def test_mixed_case_attendee_report_exports_existing_numbers(stored_event):
    event, attendee, _ = stored_event
    event.open = False
    attendee.attendee_number = 1
    attendee.extras_attendee_numbers = [2]
    source = interaction()
    await EventsCog.attendance_report.callback(EventsCog(MagicMock(spec=commands.Bot)), source, "summer bash")
    csv = source.user.send.call_args.kwargs["file"].fp.read().decode("utf-8-sig")
    assert "Alice" in csv and "Guest" in csv


async def test_mixed_case_resend_member_and_waitlist_autocomplete(stored_event):
    source = interaction()
    cog = EventsCog(MagicMock(spec=commands.Bot))
    member = MagicMock(id=123000000000000001)
    with patch("offkai_bot.cogs.events.resend_registration_details", new_callable=AsyncMock) as resend:
        resend.return_value = ([member.id], [])
        await EventsCog.resend_confirmation.callback(cog, source, "summer bash", member)
    resend.assert_awaited_once_with(stored_event[0], cog.bot, {member.id})
    source.namespace = MagicMock(event_name="summer bash")
    choices = await cog.waitlist_user_autocomplete(source, "")
    assert [choice.value for choice in choices] == ["456"]


async def test_mixed_case_payment_confirmation_finds_real_registration(stored_event, monkeypatch):
    event, attendee, _ = stored_event
    event.signup_form = {"payment_methods": {"PayNow": "instructions"}}
    bot = MagicMock(spec=discord.Client)
    bot.is_ready.return_value = True
    user = MagicMock(send=AsyncMock())
    bot.get_user.return_value = user
    monkeypatch.setattr(admin_api, "get_config", lambda: {"ADMIN_KEY": "test-key"})
    async with TestClient(TestServer(admin_api.create_admin_app(bot))) as http:
        reply = await http.post(
            "/payments/confirm",
            json={"event_name": "summer bash", "user_id": str(attendee.user_id)},
            headers={"Authorization": "Bearer test-key"},
        )
        assert reply.status == 200
    user.send.assert_awaited_once()


@pytest.mark.parametrize("apply", [False, True])
async def test_import_flags_miscased_response_keys_without_merging_them(stored_event, apply):
    payload = json.loads(export_responses_json())
    payload["summer bash"] = payload.pop("Summer Bash")
    for section in ("attendees", "waitlist"):
        for entry in payload["summer bash"][section]:
            entry["event_name"] = "summer bash"
    raw = json.dumps(payload).encode()
    file = MagicMock(size=len(raw), read=AsyncMock(return_value=raw))
    with pytest.raises(ResponsesImportError, match="does not match stored event name"):
        await EventsCog.import_responses.callback(
            EventsCog(MagicMock(spec=commands.Bot)),
            interaction(),
            file,
            apply=apply,
        )
    assert set(response_data.load_responses()) == {"Summer Bash"}
