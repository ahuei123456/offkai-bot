# tests/alerts/test_scheduler_lifecycle.py
"""Regressions for scheduler lifecycle bugs: early-fired close tasks (CONS-05),
deadlines that pass while offline (CONS-06), and deadline pings that survive a
manual close (CONS-14)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from offkai_bot.alerts import alerts
from offkai_bot.alerts.reminders import register_deadline_reminders
from offkai_bot.alerts.task import CloseOffkaiTask, DeleteRoleTask, SendMessageTask
from offkai_bot.data import event as event_data
from offkai_bot.data import response as response_data
from offkai_bot.data.event import add_event
from offkai_bot.event_actions import perform_close_event
from offkai_bot.main import load_and_update_events
from offkai_bot.util import JST


@pytest.fixture(autouse=True)
def empty_caches():
    """Start from empty in-memory data: the module's temp files are shared between tests."""
    event_data.EVENT_DATA_CACHE = []
    response_data.RESPONSE_DATA_CACHE = {}


def _scheduled() -> list:
    return [task for bucket in alerts._scheduled_tasks.values() for task in bucket]


def _future_event(*, open_: bool = True, role_id: int | None = None):
    now = datetime.now(UTC)
    event = add_event(
        event_name="Lifecycle Event",
        venue="v",
        address="a",
        google_maps_link="",
        event_datetime=now + timedelta(days=20),
        channel_id=10,
        thread_id=20,
        drinks_list=[],
        event_deadline=now + timedelta(days=10),
        ping_role_id=99,
        role_id=role_id,
    )
    event.open = open_
    return event


def _thread():
    thread = MagicMock(spec=discord.Thread)
    thread.mention = "<#20>"
    return thread


# --- CONS-05: a close task must never be consumed before its deadline ---


def test_alert_key_rounds_up_partial_minutes():
    assert alerts.alert_key(datetime(3024, 8, 15, 18, 0, 0, tzinfo=JST)) == "3024-08-15T18:00"
    assert alerts.alert_key(datetime(3024, 8, 15, 18, 0, 0, 1, tzinfo=JST)) == "3024-08-15T18:01"
    assert alerts.alert_key(datetime(3024, 8, 15, 23, 59, 50, tzinfo=JST)) == "3024-08-16T00:00"


async def test_tick_earlier_in_the_deadline_minute_does_not_consume_close_task():
    """Deadline at :50; a tick at :10 of that minute used to pop and drop the close task."""
    deadline = (datetime.now(JST) + timedelta(minutes=5)).replace(second=50, microsecond=0)
    event = MagicMock(archived=False, open=True, event_deadline=deadline)
    client = MagicMock(spec=discord.Client)
    alerts.register_alert(deadline, CloseOffkaiTask(client=client, event_name="Race Event"))

    with (
        patch("offkai_bot.alerts.task.get_event", return_value=event),
        patch("offkai_bot.alerts.task.perform_close_event", new_callable=AsyncMock) as close,
    ):
        event.is_past_deadline = False
        await alerts.fire_alert(deadline.replace(second=10))
        close.assert_not_awaited()
        assert any(isinstance(task, CloseOffkaiTask) for task in _scheduled())

        event.is_past_deadline = True
        await alerts.fire_alert(deadline + timedelta(seconds=20))  # :10 of the next minute
        close.assert_awaited_once_with(client, "Race Event", CloseOffkaiTask.close_msg)
        assert _scheduled() == []


# --- CONS-14: deadline countdown pings must not fire for a closed event ---


async def test_manual_close_suppresses_pending_deadline_pings():
    event = _future_event()
    client = MagicMock(spec=discord.Client)
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    client.get_channel.return_value = channel
    register_deadline_reminders(client, event, _thread())
    pings = [task for task in _scheduled() if isinstance(task, SendMessageTask)]
    assert len(pings) == 3

    with patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock):
        await perform_close_event(client, event.event_name)

    for ping in pings:
        await ping.action()
    channel.send.assert_not_awaited()


async def test_deadline_ping_still_sent_while_event_open():
    event = _future_event()
    client = MagicMock(spec=discord.Client)
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    client.get_channel.return_value = channel
    register_deadline_reminders(client, event, _thread())
    ping = next(task for task in _scheduled() if isinstance(task, SendMessageTask))

    await ping.action()

    channel.send.assert_awaited_once()


async def test_untagged_send_message_task_does_not_look_up_events():
    client = MagicMock(spec=discord.Client)
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    client.get_channel.return_value = channel

    with patch("offkai_bot.alerts.task.get_event") as get_event:
        await SendMessageTask(client=client, channel_id=10, message="hi").action()

    get_event.assert_not_called()
    channel.send.assert_awaited_once_with("hi")


def test_new_deadline_on_closed_event_schedules_only_role_deletion():
    """Extending the deadline of a closed event must not schedule pings or a close task."""
    event = _future_event(open_=False, role_id=555)
    register_deadline_reminders(MagicMock(spec=discord.Client), event, _thread())

    scheduled = _scheduled()
    assert len(scheduled) == 1
    assert isinstance(scheduled[0], DeleteRoleTask)


async def test_close_task_skips_already_closed_event():
    event = MagicMock(archived=False, open=False, is_past_deadline=True)
    with (
        patch("offkai_bot.alerts.task.get_event", return_value=event),
        patch("offkai_bot.alerts.task.perform_close_event", new_callable=AsyncMock) as close,
    ):
        await CloseOffkaiTask(client=MagicMock(spec=discord.Client), event_name="Closed").action()
    close.assert_not_awaited()


# --- CONS-06: startup closes open events whose deadline passed while offline ---


@patch("offkai_bot.main.register_checkin_reminder")
@patch("offkai_bot.main.register_deadline_reminders")
@patch("offkai_bot.main.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.main.update_event_message", new_callable=AsyncMock)
async def test_startup_closes_overdue_open_event(_update, _fetch, _register, _checkin):
    now = datetime.now(UTC)
    overdue = add_event(
        event_name="Overdue",
        venue="v",
        address="a",
        google_maps_link="",
        event_datetime=now + timedelta(days=2),
        channel_id=10,
        thread_id=20,
        drinks_list=[],
        event_deadline=now - timedelta(minutes=2),
    )
    on_time = _future_event()
    client = MagicMock(spec=discord.Client)

    with patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock) as close_refresh:
        await load_and_update_events(client)

    assert overdue.open is False
    assert overdue.closed_attendance_count == 0
    close_refresh.assert_awaited_once_with(client, overdue)
    assert on_time.open is True
    _update.assert_awaited_once_with(client, on_time)
