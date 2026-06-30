# tests/alerts/test_checkin_reminder.py
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from offkai_bot.alerts.reminders import (
    CHECKIN_REMINDER_LEAD,
    SendCheckinReminderTask,
    build_checkin_reminder_message,
    register_checkin_reminder,
    unregister_checkin_reminder,
)
from offkai_bot.data.event import Event
from offkai_bot.data.response import Response

from offkai_bot.alerts import alerts

# --- Fixtures ---


@pytest.fixture(autouse=True)
def clear_scheduled_tasks():
    original = alerts._scheduled_tasks.copy()
    alerts._scheduled_tasks.clear()
    yield
    alerts._scheduled_tasks = original


@pytest.fixture
def mock_client():
    return MagicMock(spec=discord.Client)


def _event(event_dt: datetime | None = None, archived: bool = False) -> Event:
    event_dt = event_dt or (datetime.now(UTC) + timedelta(days=5))
    return Event(
        event_name="Future Offkai",
        venue="Test Venue",
        address="123 Test Street, Tokyo",
        google_maps_link="https://maps.example/x",
        event_datetime=event_dt,
        event_deadline=event_dt - timedelta(days=2),
        channel_id=111,
        thread_id=222,
        message_id=None,
        open=True,
        archived=archived,
        drinks=["Highball (L)"],
    )


def _response(
    user_id: int,
    *,
    extra_people: int = 0,
    extras_names=None,
    drinks=None,
    attendee_number: int | None = None,
    extras_attendee_numbers=None,
) -> Response:
    return Response(
        user_id=user_id,
        username=f"user{user_id}",
        extra_people=extra_people,
        behavior_confirmed=True,
        arrival_confirmed=False,
        event_name="Future Offkai",
        timestamp=datetime.now(UTC),
        drinks=drinks or [],
        extras_names=extras_names or [],
        display_name=f"User {user_id}",
        attendee_number=attendee_number,
        extras_attendee_numbers=extras_attendee_numbers or [],
    )


def _key(dt: datetime) -> str:
    return dt.astimezone(alerts.JST).strftime(alerts._TIME_KEY_FORMAT)


# --- Scheduling: register / unregister ---


@patch("offkai_bot.alerts.reminders.register_alert")
def test_registers_exactly_24h_before_start(mock_register_alert, mock_client):
    event = _event()
    register_checkin_reminder(mock_client, event)

    assert timedelta(hours=24) == CHECKIN_REMINDER_LEAD
    mock_register_alert.assert_called_once_with(
        event.event_datetime - timedelta(hours=24),
        SendCheckinReminderTask(client=mock_client, event_name="Future Offkai"),
    )


@patch("offkai_bot.alerts.reminders.register_alert")
def test_archived_event_not_scheduled(mock_register_alert, mock_client):
    register_checkin_reminder(mock_client, _event(archived=True))
    mock_register_alert.assert_not_called()


def test_past_reminder_timestamp_skipped(mock_client):
    # Event is in the past -> reminder time is in the past -> suppressed silently.
    register_checkin_reminder(mock_client, _event(event_dt=datetime.now(UTC) - timedelta(hours=1)))
    assert alerts._scheduled_tasks == {}


def test_registering_twice_replaces_not_duplicates(mock_client):
    event = _event()
    register_checkin_reminder(mock_client, event)
    register_checkin_reminder(mock_client, event)

    tasks = [t for bucket in alerts._scheduled_tasks.values() for t in bucket if isinstance(t, SendCheckinReminderTask)]
    assert len(tasks) == 1


def test_modify_reregisters_at_updated_datetime(mock_client):
    event = _event(event_dt=datetime.now(UTC) + timedelta(days=5))
    register_checkin_reminder(mock_client, event)
    old_key = _key(event.event_datetime - CHECKIN_REMINDER_LEAD)
    assert old_key in alerts._scheduled_tasks

    # Simulate /modify_offkai changing the time.
    event.event_datetime = datetime.now(UTC) + timedelta(days=8)
    register_checkin_reminder(mock_client, event)
    new_key = _key(event.event_datetime - CHECKIN_REMINDER_LEAD)

    assert old_key not in alerts._scheduled_tasks
    assert new_key in alerts._scheduled_tasks
    tasks = [t for bucket in alerts._scheduled_tasks.values() for t in bucket if isinstance(t, SendCheckinReminderTask)]
    assert len(tasks) == 1


def test_archiving_removes_pending_reminder(mock_client):
    event = _event()
    register_checkin_reminder(mock_client, event)
    assert any(isinstance(t, SendCheckinReminderTask) for bucket in alerts._scheduled_tasks.values() for t in bucket)

    unregister_checkin_reminder(event.event_name)
    assert not any(
        isinstance(t, SendCheckinReminderTask) for bucket in alerts._scheduled_tasks.values() for t in bucket
    )


def test_unregister_leaves_other_events_intact(mock_client):
    e1 = _event(event_dt=datetime.now(UTC) + timedelta(days=5))
    e2 = _event(event_dt=datetime.now(UTC) + timedelta(days=6))
    e2.event_name = "Other Offkai"
    register_checkin_reminder(mock_client, e1)
    register_checkin_reminder(mock_client, e2)

    unregister_checkin_reminder("Future Offkai")
    remaining = [
        t for bucket in alerts._scheduled_tasks.values() for t in bucket if isinstance(t, SendCheckinReminderTask)
    ]
    assert len(remaining) == 1
    assert remaining[0].event_name == "Other Offkai"


# --- Message content ---


def test_message_includes_core_fields_and_optional_lines():
    event = _event()
    resp = _response(123, extra_people=2, extras_names=["Senpai", "Kouhai"], drinks=["Highball (L)", "Oolong Tea (L)"])
    msg = build_checkin_reminder_message(event, resp, "https://offkai.example/?token=123.abc")

    assert "Reminder: Future Offkai is tomorrow!" in msg
    assert "リマインダー: Future Offkai は明日開催です！" in msg
    assert "Test Venue" in msg
    assert "123 Test Street, Tokyo" in msg
    assert "JST" in msg
    assert "**Bringing:** 2 extra guests" in msg
    assert "**同伴者:** 2名" in msg
    assert "Guest names: Senpai, Kouhai" in msg
    assert "同伴者名: Senpai, Kouhai" in msg
    assert "Drinks: Highball (L), Oolong Tea (L)" in msg
    assert "飲み物: Highball (L), Oolong Tea (L)" in msg
    assert "https://offkai.example/?token=123.abc" in msg
    assert "Please show the QR code at the door for check-in." in msg
    assert "受付でQRコードをご提示ください。" in msg
    # No late-withdrawal warning carried over from signup confirmation.
    assert "withdraw" not in msg.lower()


def test_message_omits_optional_lines_when_empty():
    msg = build_checkin_reminder_message(_event(), _response(123), "https://offkai.example/?token=123.abc")
    assert "Guest names:" not in msg
    assert "同伴者名:" not in msg
    assert "Drinks:" not in msg
    assert "飲み物:" not in msg
    assert "Attendee Number" not in msg
    assert "受付番号" not in msg
    assert "**Bringing:** 0 extra guests" in msg


def test_message_includes_attendee_number_lines():
    resp = _response(
        123,
        extra_people=2,
        extras_names=["Senpai", "Kouhai"],
        attendee_number=7,
        extras_attendee_numbers=[8, 9],
    )

    msg = build_checkin_reminder_message(_event(), resp, "https://offkai.example/?token=123.abc")

    assert "**Attendee Numbers:** 7 (you), 8 (Senpai), 9 (Kouhai)" in msg
    assert "**受付番号:** 7（本人）, 8（Senpai）, 9（Kouhai）" in msg


def test_message_includes_single_attendee_number_line():
    msg = build_checkin_reminder_message(
        _event(),
        _response(123, attendee_number=7),
        "https://offkai.example/?token=123.abc",
    )

    assert "**Attendee Number:** 7 (you)" in msg
    assert "**受付番号:** 7（本人）" in msg


def test_message_omits_qr_lines_when_no_frontend_url():
    msg = build_checkin_reminder_message(_event(), _response(123), "")
    assert "RSVP Page / QR Code" not in msg
    assert "RSVPページ" not in msg
    # No QR link -> no door-QR instruction either (would be meaningless).
    assert "Please show the QR code at the door for check-in." not in msg
    assert "受付でQRコードをご提示ください。" not in msg
    # Core details are still present.
    assert "Reminder: Future Offkai is tomorrow!" in msg
    assert "リマインダー: Future Offkai は明日開催です！" in msg


# --- Send-time behaviour ---


@pytest.mark.asyncio
@patch("offkai_bot.alerts.reminders.asyncio.sleep", new_callable=AsyncMock)
@patch("offkai_bot.alerts.reminders.build_checkin_url")
@patch("offkai_bot.alerts.reminders.get_responses")
@patch("offkai_bot.alerts.reminders.get_event")
async def test_task_reloads_and_dms_each_confirmed_attendee(
    mock_get_event, mock_get_responses, mock_build_url, _mock_sleep, mock_client
):
    event = _event()
    mock_get_event.return_value = event
    mock_get_responses.return_value = [_response(1), _response(2), _response(3)]
    mock_build_url.return_value = "https://offkai.example/?token=1.abc"

    users = [MagicMock() for _ in range(3)]
    for u in users:
        u.send = AsyncMock()
    mock_client.fetch_user = AsyncMock(side_effect=users)

    task = SendCheckinReminderTask(client=mock_client, event_name="Future Offkai")
    await task.action()
    assert task._fan_out_task is not None
    await task._fan_out_task

    # Reloaded event + attendees at send time.
    mock_get_event.assert_called_once_with("Future Offkai")
    mock_get_responses.assert_called_once_with("Future Offkai")
    # One DM per attendee; never a channel send.
    assert mock_client.fetch_user.await_count == 3
    for u in users:
        u.send.assert_awaited_once()
    mock_client.get_channel.assert_not_called()
    # Sleep only between sends (3 attendees -> 2 sleeps).
    assert _mock_sleep.await_count == 2


@pytest.mark.asyncio
@patch("offkai_bot.alerts.reminders.asyncio.sleep", new_callable=AsyncMock)
@patch("offkai_bot.alerts.reminders.build_checkin_url")
@patch("offkai_bot.alerts.reminders.get_responses")
@patch("offkai_bot.alerts.reminders.get_event")
async def test_action_returns_immediately_scheduling_background_task(
    mock_get_event, mock_get_responses, mock_build_url, _mock_sleep, mock_client
):
    """action() must return before _send_dms completes so it doesn't stall alert_loop."""
    mock_get_event.return_value = _event()
    mock_get_responses.return_value = [_response(1), _response(2)]
    mock_build_url.return_value = ""

    # Use a gate that _send_dms must reach before we can assert it is running.
    started = asyncio.Event()
    original_fetch = AsyncMock(side_effect=lambda uid: started.set() or MagicMock(send=AsyncMock()))

    mock_client.fetch_user = original_fetch

    task = SendCheckinReminderTask(client=mock_client, event_name="Future Offkai")
    await task.action()

    # action() returned; background task exists but may not have started yet.
    assert task._fan_out_task is not None
    assert isinstance(task._fan_out_task, asyncio.Task)
    assert not task._fan_out_task.done()

    # Let the event loop run and confirm it completes.
    await task._fan_out_task
    assert task._fan_out_task.done()


@pytest.mark.asyncio
@patch("offkai_bot.alerts.reminders.asyncio.sleep", new_callable=AsyncMock)
@patch("offkai_bot.alerts.reminders.get_responses")
@patch("offkai_bot.alerts.reminders.get_event")
async def test_task_skips_when_event_missing(mock_get_event, mock_get_responses, _sleep, mock_client):
    from offkai_bot.errors import EventNotFoundError

    mock_get_event.side_effect = EventNotFoundError("Future Offkai")
    mock_client.fetch_user = AsyncMock()

    task = SendCheckinReminderTask(client=mock_client, event_name="Future Offkai")
    await task.action()

    # Early return — no fan-out task created.
    assert task._fan_out_task is None
    mock_get_responses.assert_not_called()
    mock_client.fetch_user.assert_not_awaited()


@pytest.mark.asyncio
@patch("offkai_bot.alerts.reminders.asyncio.sleep", new_callable=AsyncMock)
@patch("offkai_bot.alerts.reminders.get_responses")
@patch("offkai_bot.alerts.reminders.get_event")
async def test_task_skips_archived_event(mock_get_event, mock_get_responses, _sleep, mock_client):
    mock_get_event.return_value = _event(archived=True)
    mock_client.fetch_user = AsyncMock()

    task = SendCheckinReminderTask(client=mock_client, event_name="Future Offkai")
    await task.action()

    assert task._fan_out_task is None
    mock_get_responses.assert_not_called()
    mock_client.fetch_user.assert_not_awaited()


@pytest.mark.asyncio
@patch("offkai_bot.alerts.reminders.asyncio.sleep", new_callable=AsyncMock)
@patch("offkai_bot.alerts.reminders.get_responses")
@patch("offkai_bot.alerts.reminders.get_event")
async def test_task_no_attendees(mock_get_event, mock_get_responses, _sleep, mock_client):
    mock_get_event.return_value = _event()
    mock_get_responses.return_value = []
    mock_client.fetch_user = AsyncMock()

    task = SendCheckinReminderTask(client=mock_client, event_name="Future Offkai")
    await task.action()

    assert task._fan_out_task is None
    mock_client.fetch_user.assert_not_awaited()


@pytest.mark.asyncio
@patch("offkai_bot.alerts.reminders.asyncio.sleep", new_callable=AsyncMock)
@patch("offkai_bot.alerts.reminders.build_checkin_url")
@patch("offkai_bot.alerts.reminders.get_responses")
@patch("offkai_bot.alerts.reminders.get_event")
async def test_blocked_dm_does_not_stop_others_or_fall_back_to_channel(
    mock_get_event, mock_get_responses, mock_build_url, _sleep, mock_client
):
    mock_get_event.return_value = _event()
    mock_get_responses.return_value = [_response(1), _response(2)]
    mock_build_url.return_value = ""

    blocked = MagicMock()
    blocked.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "blocked"))
    ok = MagicMock()
    ok.send = AsyncMock()
    mock_client.fetch_user = AsyncMock(side_effect=[blocked, ok])

    task = SendCheckinReminderTask(client=mock_client, event_name="Future Offkai")
    await task.action()
    await task._fan_out_task

    blocked.send.assert_awaited_once()
    ok.send.assert_awaited_once()
    # No public-channel fallback of any kind.
    mock_client.get_channel.assert_not_called()


@pytest.mark.asyncio
@patch("offkai_bot.alerts.reminders.asyncio.sleep", new_callable=AsyncMock)
@patch("offkai_bot.alerts.reminders.build_checkin_url")
@patch("offkai_bot.alerts.reminders.get_responses")
@patch("offkai_bot.alerts.reminders.get_event")
async def test_no_waitlist_user_is_dmed(mock_get_event, mock_get_responses, mock_build_url, _sleep, mock_client):
    # The task only ever consults get_responses (confirmed attendees).
    mock_get_event.return_value = _event()
    mock_get_responses.return_value = [_response(1)]
    mock_build_url.return_value = ""

    user = MagicMock()
    user.send = AsyncMock()
    mock_client.fetch_user = AsyncMock(return_value=user)

    task = SendCheckinReminderTask(client=mock_client, event_name="Future Offkai")
    await task.action()
    await task._fan_out_task

    mock_client.fetch_user.assert_awaited_once_with(1)


@pytest.mark.asyncio
@patch("offkai_bot.alerts.reminders.asyncio.sleep", new_callable=AsyncMock)
@patch("offkai_bot.alerts.reminders.build_checkin_url")
@patch("offkai_bot.alerts.reminders.get_responses")
@patch("offkai_bot.alerts.reminders.get_event")
async def test_logs_never_leak_token_url_or_body(
    mock_get_event, mock_get_responses, mock_build_url, _sleep, mock_client, caplog
):
    mock_get_event.return_value = _event()
    mock_get_responses.return_value = [_response(1), _response(2)]
    mock_build_url.return_value = "https://offkai.example/?token=1.abcdef1234567890"

    ok = MagicMock()
    ok.send = AsyncMock()
    blocked = MagicMock()
    blocked.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "blocked"))
    mock_client.fetch_user = AsyncMock(side_effect=[ok, blocked])

    task = SendCheckinReminderTask(client=mock_client, event_name="Future Offkai")
    with caplog.at_level("DEBUG"):
        await task.action()
        await task._fan_out_task

    text = caplog.text
    assert "token=" not in text
    assert "/?token=" not in text
    assert "https://offkai.example" not in text
    # No reminder body lines in logs.
    assert "Please show the QR code at the door" not in text
    assert "RSVP Page / QR Code" not in text


@pytest.mark.asyncio
@patch("offkai_bot.alerts.reminders.asyncio.sleep", new_callable=AsyncMock)
@patch("offkai_bot.alerts.reminders.build_checkin_url")
@patch("offkai_bot.alerts.reminders.get_responses")
@patch("offkai_bot.alerts.reminders.get_event")
async def test_token_shape_is_userid_dot_signature(
    mock_get_event, mock_get_responses, mock_build_url, _sleep, mock_client
):
    mock_get_event.return_value = _event()
    mock_get_responses.return_value = [_response(4242)]
    # build_checkin_url now owns token construction; test it directly in test_util.py.
    # Here we just verify the URL it returns ends up in the DM body unchanged.
    mock_build_url.return_value = "https://offkai.example/?token=4242.abcdef1234567890"

    user = MagicMock()
    user.send = AsyncMock()
    mock_client.fetch_user = AsyncMock(return_value=user)

    task = SendCheckinReminderTask(client=mock_client, event_name="Future Offkai")
    await task.action()
    await task._fan_out_task

    sent_body = user.send.await_args.args[0]
    assert "https://offkai.example/?token=4242.abcdef1234567890" in sent_body
