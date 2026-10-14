"""Expired payment choices release the whole group without reviving stale work."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from offkai_bot.data import event as events
from offkai_bot.data import response as responses
from offkai_bot.data.event import Event
from offkai_bot.interactions import send_signup_reply
from offkai_bot.role_management import assign_event_role, remove_event_role


@pytest.fixture
def expired_registration():
    now = datetime.now(UTC)
    event = Event("Expiry", "Venue", "Address", "", now + timedelta(days=7), open=True, max_capacity=3)
    event.signup_form = {"payment_methods": {"Bank": "Secret instructions"}}
    events.EVENT_DATA_CACHE = [event]
    entry = responses.Response(
        123,
        "Alice",
        2,
        True,
        True,
        event.event_name,
        now - timedelta(days=3),
        extras_names=["Guest A", "Guest B"],
        drinks=["Tea"],
        no_show_agreed=True,
        attendee_number=1,
        extras_attendee_numbers=[2, 3],
        payment_selection_expires_at=now,
    )
    waiting = responses.WaitlistEntry(456, "Bob", 0, True, True, event.event_name, now)
    responses.RESPONSE_DATA_CACHE = {event.event_name: {"attendees": [entry], "waitlist": [waiting]}}
    return event, entry, waiting, now


def test_expiry_moves_group_to_tail_atomically(expired_registration):
    event, entry, waiting, now = expired_registration
    moved = responses.expire_payment_selections(event, now)
    assert [r.user_id for r in moved] == [entry.user_id]
    assert responses.get_responses(event.event_name) == []
    queued = responses.get_waitlist(event.event_name)
    assert [r.user_id for r in queued] == [waiting.user_id, entry.user_id]
    assert queued[-1].extra_people == 2 and queued[-1].extras_names == entry.extras_names
    assert queued[-1].timestamp == entry.timestamp and queued[-1].no_show_agreed
    assert queued[-1].drinks == ["Tea"] and queued[-1].payment_method is None
    assert responses.expire_payment_selections(event, now) == []
    responses.RESPONSE_DATA_CACHE = None
    assert [r.user_id for r in responses.get_waitlist(event.event_name)] == [456, 123]


async def test_withdrawal_during_promotion_fetch_suppresses_dm(expired_registration):
    event, entry, _, _ = expired_registration
    responses.remove_response(event.event_name, entry.user_id)
    send = AsyncMock()
    await send_signup_reply(send, event, entry, "Attendance confirmed", "Confirmed", promotion=True)
    send.assert_not_awaited()


async def test_withdrawal_during_role_add_removes_late_role(expired_registration):
    event, entry, _, _ = expired_registration
    entered, release = asyncio.Event(), asyncio.Event()
    role = MagicMock(spec=discord.Role)
    member = MagicMock(spec=discord.Member, roles=[], remove_roles=AsyncMock())

    async def add_roles(*args, **kwargs):
        entered.set()
        await release.wait()

    member.add_roles = AsyncMock(side_effect=add_roles)
    guild = MagicMock(spec=discord.Guild)
    guild.get_role.return_value = role
    guild.get_member.return_value = member
    guild.fetch_member = AsyncMock(return_value=member)
    task = asyncio.create_task(assign_event_role(guild, entry.user_id, 999, event=event))
    await entered.wait()
    responses.remove_response(event.event_name, entry.user_id)
    release.set()
    await task
    member.remove_roles.assert_awaited_once()


@pytest.mark.parametrize("change", ["chosen", "not_due", "archived", "interest", "disabled"])
def test_expiry_ignores_ineligible_registration(expired_registration, change):
    event, entry, _, now = expired_registration
    if change == "chosen":
        entry.payment_method = "Bank"
    elif change == "not_due":
        entry.payment_selection_expires_at = now + timedelta(seconds=1)
    elif change == "archived":
        event.archived = True
    elif change == "interest":
        event.interest_check = True
    else:
        event.signup_form["payment_methods"] = {}
    assert responses.expire_payment_selections(event, now) == []
    assert responses.get_responses(event.event_name) == [entry]


def test_expiry_write_failure_retries_without_partial_move(expired_registration):
    event, entry, waiting, now = expired_registration
    with (
        patch("offkai_bot.data.response.atomic_write_json", side_effect=OSError("Disk failure")),
        pytest.raises(OSError),
    ):
        responses.expire_payment_selections(event, now)
    assert responses.get_responses(event.event_name) == [entry]
    assert responses.get_waitlist(event.event_name) == [waiting]
    assert responses.expire_payment_selections(event, now) == [entry]


@pytest.mark.parametrize("has_waiting", [False, True])
async def test_restart_sweep_backfills_without_immediate_repromotion(expired_registration, has_waiting):
    from offkai_bot.payment_selection import expire_pending_payments

    event, entry, waiting, _ = expired_registration
    if not has_waiting:
        responses.remove_from_waitlist(event.event_name, waiting.user_id)
    responses.save_responses()
    responses.RESPONSE_DATA_CACHE = None  # Catch up a deadline missed while the bot was offline.
    client = MagicMock(spec=discord.Client)
    user = MagicMock(spec=discord.User, send=AsyncMock())
    client.get_user.return_value = user
    client.fetch_user = AsyncMock(return_value=user)
    with patch("offkai_bot.payment_selection.update_event_message", new=AsyncMock()):
        await expire_pending_payments(client)
        assert [w.user_id for w in responses.get_waitlist(event.event_name)] == [123]
        confirmed = responses.get_responses(event.event_name)
        assert [r.user_id for r in confirmed] == ([456] if has_waiting else [])
        sends = user.send.await_count
        await expire_pending_payments(client)
        assert user.send.await_count == sends
    # Organizer promotion works even if capacity is zero, with a new 72-hour window.
    event.max_capacity = 0
    promoted = responses.promote_waitlist_response(event, entry.user_id)
    assert promoted.payment_selection_expires_at > datetime.now(UTC) + timedelta(hours=71)


async def test_withdrawal_during_dm_delivery_deletes_late_confirmation(expired_registration):
    event, entry, _, now = expired_registration
    entry.payment_selection_expires_at = now + timedelta(hours=72)
    message = MagicMock(spec=discord.Message, delete=AsyncMock())

    async def send(*args, **kwargs):
        responses.remove_response(event.event_name, entry.user_id)
        return message

    await send_signup_reply(send, event, entry, "Attendance confirmed", "Confirmed", promotion=True)
    message.delete.assert_awaited_once()


async def test_rejoin_during_role_removal_restores_role(expired_registration):
    event, entry, _, _ = expired_registration
    responses.remove_response(event.event_name, entry.user_id)
    role = MagicMock(spec=discord.Role)
    member = MagicMock(spec=discord.Member, roles=[role], add_roles=AsyncMock())

    async def remove_roles(*args, **kwargs):
        responses.add_response(event.event_name, replace(entry, timestamp=datetime.now(UTC)))

    member.remove_roles = AsyncMock(side_effect=remove_roles)
    guild = MagicMock(spec=discord.Guild)
    guild.get_role.return_value = role
    guild.get_member.return_value = member
    guild.fetch_member = AsyncMock(return_value=member)
    await remove_event_role(guild, entry.user_id, 999, event=event)
    member.add_roles.assert_awaited_once()


async def test_alert_tick_runs_saved_expiry_processing(expired_registration, monkeypatch):
    from offkai_bot.alerts import alerts

    event, _, waiting, _ = expired_registration
    responses.remove_from_waitlist(event.event_name, waiting.user_id)
    client = MagicMock(spec=discord.Client)
    client.get_user.return_value = MagicMock(spec=discord.User, send=AsyncMock())
    monkeypatch.setattr(alerts, "_client", client)
    with (
        patch.object(alerts, "fire_alert", new=AsyncMock()),
        patch("offkai_bot.payment_selection.update_event_message", new=AsyncMock()),
    ):
        await alerts.alert_loop.coro()
    assert responses.get_responses(event.event_name) == []
    assert [r.user_id for r in responses.get_waitlist(event.event_name)] == [123]


def test_expired_window_cannot_save_choice_after_demotion(expired_registration):
    event, entry, _, now = expired_registration
    responses.expire_payment_selections(event, now)
    with pytest.raises(ValueError):
        responses.complete_payment_selection(
            event.event_name, entry.user_id, entry.timestamp, entry.payment_selection_expires_at, "Bank"
        )
    assert responses.get_responses(event.event_name) == []


async def test_overlapping_sweeps_and_manual_repromotion_do_not_send_stale_expiry(expired_registration):
    from offkai_bot.payment_selection import expire_pending_payments

    event, entry, _, _ = expired_registration
    entered, release = asyncio.Event(), asyncio.Event()
    user = MagicMock(spec=discord.User, send=AsyncMock())

    async def fetch_user(user_id):
        entered.set()
        await release.wait()
        return user

    client = MagicMock(spec=discord.Client)
    client.get_user.return_value = None
    client.fetch_user = AsyncMock(side_effect=fetch_user)
    with patch("offkai_bot.payment_selection.update_event_message", new=AsyncMock()):
        first = asyncio.create_task(expire_pending_payments(client))
        await entered.wait()  # Demotion saved, before the expiry notification.
        await expire_pending_payments(client)
        promoted = responses.promote_waitlist_response(event, entry.user_id)
        deadline = promoted.payment_selection_expires_at
        release.set()
        await first
    user.send.assert_not_awaited()
    assert responses.get_responses(event.event_name) == [promoted]
    assert promoted.payment_selection_expires_at == deadline
