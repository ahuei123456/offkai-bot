"""Failure, concurrency and lifecycle cases found by the PR reviewer."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from aiohttp import ClientConnectionError
from aiohttp.test_utils import TestClient, TestServer

from offkai_bot import admin_api
from offkai_bot.data import event as events
from offkai_bot.data import response as responses
from offkai_bot.data.event import Event
from offkai_bot.interactions import GatheringModal, PromotedPaymentSelection, SignupContext, _add_user_to_event_thread

from .test_custom_signup import interaction


def waiting_entry(record):
    return responses.WaitlistEntry(
        **{key: getattr(record, key) for key in responses.WaitlistEntry.__dataclass_fields__}
    )


@pytest.fixture
def record():
    entry = responses.Response(191524132624531458, "Synthetic", 0, True, True, "Review", datetime.now(UTC))
    responses.RESPONSE_DATA_CACHE = {"Review": {"attendees": [entry], "waitlist": []}}
    return entry


@pytest.fixture
def event(record):
    value = Event(
        "Review",
        "Venue",
        "Address",
        "",
        datetime.now(UTC) + timedelta(days=7),
        thread_id=999,
        signup_form={"payment_methods": {"Bank": "Private instructions"}},
    )
    events.EVENT_DATA_CACHE = [value]
    return value


@pytest.mark.parametrize("operation", ["add", "remove", "waitlist_add", "waitlist_remove"])
def test_registration_write_failure_never_publishes_cache_change(record, operation, mock_paths):
    before = responses.RESPONSE_DATA_CACHE["Review"]
    if operation.startswith("waitlist"):
        before["attendees"] = []
        before["waitlist"] = [] if operation.endswith("add") else [waiting_entry(record)]
    elif operation == "add":
        before["attendees"] = []
    attendees, waiting = list(before["attendees"]), list(before["waitlist"])
    responses.save_responses()
    from pathlib import Path

    disk = Path(mock_paths["responses"]).read_bytes()
    with patch("offkai_bot.data.response.atomic_write_json", side_effect=OSError("Disk full")), pytest.raises(OSError):
        if operation == "add":
            responses.add_response("Review", record)
        elif operation == "remove":
            responses.remove_response("Review", record.user_id)
        elif operation == "waitlist_add":
            responses.add_to_waitlist("Review", waiting_entry(record))
        else:
            responses.remove_from_waitlist("Review", record.user_id)
    assert responses.RESPONSE_DATA_CACHE["Review"]["attendees"] == attendees
    assert responses.RESPONSE_DATA_CACHE["Review"]["waitlist"] == waiting
    assert Path(mock_paths["responses"]).read_bytes() == disk


async def test_reply_connection_error_does_not_skip_membership(event, record):
    source = interaction(record.user_id)
    source.user.send.side_effect = ClientConnectionError("Connection reset")
    with (
        patch("offkai_bot.interactions._add_user_to_event_thread", new=AsyncMock()) as join,
        patch("offkai_bot.interactions.update_rank"),
        patch("offkai_bot.interactions.get_rank", return_value=0),
    ):
        await GatheringModal(event=event)._handle_successful_submission(source, record)
    join.assert_awaited_once()


@pytest.mark.parametrize("during", ["lookup", "add"])
async def test_withdrawal_during_discord_request_leaves_no_membership(event, record, during):
    thread = MagicMock(
        spec=discord.Thread, id=999, archived=False, locked=False, add_user=AsyncMock(), remove_user=AsyncMock()
    )

    async def withdraw(*args):
        responses.remove_response("Review", record.user_id)
        return thread

    bot = MagicMock(spec=discord.Client, fetch_channel=AsyncMock(return_value=thread))
    bot.get_channel.return_value = None
    if during == "lookup":
        bot.fetch_channel.side_effect = withdraw
    else:
        thread.add_user.side_effect = withdraw
    await _add_user_to_event_thread(event, SignupContext(None, None, discord.Object(id=record.user_id)), bot)
    if during == "lookup":
        thread.add_user.assert_not_awaited()
    else:
        thread.remove_user.assert_awaited_once()


@pytest.mark.parametrize("waitlisted", [False, True])
async def test_admin_payment_confirmation_accepts_historical_registration(event, record, waitlisted):
    if waitlisted:
        responses.RESPONSE_DATA_CACHE["Review"] = {
            "attendees": [],
            "waitlist": [waiting_entry(record)],
        }
    user = MagicMock(spec=discord.User, send=AsyncMock())
    bot = MagicMock(spec=discord.Client)
    bot.is_ready.return_value = True
    bot.get_user.return_value = user
    with patch("offkai_bot.admin_api.get_config", return_value={"ADMIN_KEY": "test"}):
        async with TestClient(TestServer(admin_api.create_admin_app(bot))) as http:
            payload = {"event_name": "Review", "user_id": str(record.user_id)}
            assert (await http.post("/payments/confirm", json=payload)).status == 401
            reply = await http.post("/payments/confirm", json=payload, headers={"Authorization": "Bearer test"})
            assert reply.status == 200
    user.send.assert_awaited_once()


async def test_payment_view_stops_at_absolute_deadline_even_without_clicks(event, record):
    record.payment_selection_expires_at = datetime.now(UTC) + timedelta(milliseconds=20)
    view = PromotedPaymentSelection(event, record)
    assert view.is_persistent()
    client = discord.Client(intents=discord.Intents.none())
    client.add_view(view)
    assert view in client.persistent_views
    await asyncio.sleep(0.05)
    assert view.is_finished()
    assert view not in client.persistent_views


async def test_old_join_does_not_apply_to_rejoined_registration(event, record):
    thread = MagicMock(spec=discord.Thread, id=999, archived=False, locked=False, add_user=AsyncMock())

    async def rejoin(*args):
        responses.remove_response("Review", record.user_id)
        responses.add_response("Review", replace(record, timestamp=record.timestamp + timedelta(seconds=1)))
        return thread

    bot = MagicMock(spec=discord.Client, fetch_channel=AsyncMock(side_effect=rejoin))
    bot.get_channel.return_value = None
    await _add_user_to_event_thread(event, SignupContext(None, None, discord.Object(id=record.user_id)), bot)
    thread.add_user.assert_not_awaited()


async def test_old_withdrawal_does_not_remove_rejoined_member(event, record):
    from offkai_bot.interactions import remove_event_thread_member

    thread = MagicMock(spec=discord.Thread, remove_user=AsyncMock())
    await remove_event_thread_member(event, thread, discord.Object(id=record.user_id))
    thread.remove_user.assert_not_awaited()


async def test_withdrawal_cleanup_waits_for_inflight_membership(event, record):
    from offkai_bot.interactions import remove_event_thread_member

    started, release = asyncio.Event(), asyncio.Event()

    async def join(*args):
        started.set()
        await release.wait()

    thread = MagicMock(
        spec=discord.Thread,
        id=999,
        archived=False,
        locked=False,
        add_user=AsyncMock(side_effect=join),
        remove_user=AsyncMock(),
    )
    user = discord.Object(id=record.user_id)
    adding = asyncio.create_task(_add_user_to_event_thread(event, SignupContext(thread, None, user), MagicMock()))
    await started.wait()
    responses.remove_response("Review", record.user_id)
    removing = asyncio.create_task(remove_event_thread_member(event, thread, user))
    await asyncio.sleep(0)
    thread.remove_user.assert_not_awaited()
    release.set()
    await asyncio.gather(adding, removing)
    assert thread.remove_user.await_count >= 1
    assert not responses.get_responses("Review")


async def test_failed_delivery_stops_unregistered_payment_view(event, record):
    from offkai_bot.interactions import send_signup_reply

    record.payment_selection_expires_at = datetime.now(UTC) + timedelta(hours=72)
    send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "DM blocked"))
    with pytest.raises(discord.Forbidden):
        await send_signup_reply(send, event, record, "Attendance confirmed", "Confirmed")
    view = send.call_args.kwargs["view"]
    assert view.is_finished()
    assert view._expiry_handle.cancelled()
