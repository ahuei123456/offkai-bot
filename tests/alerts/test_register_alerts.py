# tests/alerts/test_alerts.py

from datetime import UTC, datetime, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import discord
import pytest

# Import the module and functions to test
from offkai_bot.alerts import alerts
from offkai_bot.alerts.task import CloseOffkaiTask, SendMessageTask, Task  # Import base Task for type hinting
from offkai_bot.data.event import Event
from offkai_bot.errors import AlertTimeInPastError
from offkai_bot.event_actions import register_deadline_reminders
from offkai_bot.util import JST  # Import the JST timezone object

# --- Fixtures ---


@pytest.fixture(autouse=True)
def clear_scheduled_tasks():
    """Fixture to automatically clear the global _scheduled_tasks before/after each test."""
    original_tasks = alerts._scheduled_tasks.copy()  # Store original (should be empty)
    alerts._scheduled_tasks.clear()  # Clear before test
    yield  # Run the test
    alerts._scheduled_tasks = original_tasks  # Restore original after test


@pytest.fixture
def mock_client():
    """Fixture for a mock discord.Client."""
    return MagicMock(spec=discord.Client)


@pytest.fixture
def mock_task(mock_client):
    """Fixture for a mock Task object."""
    task = MagicMock(spec=Task)
    # Mock the action method as an async function
    task.action = AsyncMock()
    # Mock the client attribute
    task.client = mock_client
    # Mock class name for logging purposes
    task.__class__.__name__ = "MockTask"
    return task


@pytest.fixture
def mock_thread():
    """Fixture for a mock discord.Thread."""
    thread = MagicMock(spec=discord.Thread)
    thread.mention = ""

    return thread


@pytest.fixture
def future_event():
    """Fixture for a basic event set in the future with a deadline and channel ID."""
    now_utc = datetime.now(UTC)
    deadline_utc = now_utc + timedelta(days=10)  # Deadline 10 days from now
    event_dt_utc = deadline_utc + timedelta(days=5)  # Event 5 days after deadline
    return Event(
        event_name="Future Event",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=event_dt_utc,
        event_deadline=deadline_utc,
        channel_id=123456789,  # Assign a channel ID
        thread_id=987654321,
        message_id=None,
        open=True,
        archived=False,
        drinks=[],
        message="Future Event Message",
    )


# --- Tests for register_alert ---


@patch("offkai_bot.alerts.alerts._log")
def test_register_alert_naive_datetime(mock_log, mock_task):
    """Test registering an alert with a naive datetime (assumed JST)."""
    # Arrange
    naive_dt = datetime(3024, 8, 15, 10, 30, 0)  # Example naive time
    expected_jst_dt = naive_dt.replace(tzinfo=JST)
    expected_key = expected_jst_dt.strftime(alerts._TIME_KEY_FORMAT)

    # Act
    alerts.register_alert(naive_dt, mock_task)

    # Assert
    assert expected_key in alerts._scheduled_tasks
    assert alerts._scheduled_tasks[expected_key] == [mock_task]
    mock_log.debug.assert_called_once_with(
        f"Registering alert: Naive time {naive_dt} assumed JST -> {expected_jst_dt.isoformat()}"
    )
    mock_log.info.assert_called_once()


@patch("offkai_bot.alerts.alerts._log")
def test_register_alert_aware_datetime_utc(mock_log, mock_task):
    """Test registering an alert with an aware UTC datetime."""
    # Arrange
    aware_utc_dt = datetime(3024, 8, 15, 1, 30, 0, tzinfo=UTC)  # UTC time
    expected_jst_dt = aware_utc_dt.astimezone(JST)  # Should be 10:30 JST
    expected_key = expected_jst_dt.strftime(alerts._TIME_KEY_FORMAT)

    # Act
    alerts.register_alert(aware_utc_dt, mock_task)

    # Assert
    assert expected_key in alerts._scheduled_tasks
    assert alerts._scheduled_tasks[expected_key] == [mock_task]
    mock_log.debug.assert_called_once_with(
        f"Registering alert: Aware time {aware_utc_dt.isoformat()} converted to JST -> {expected_jst_dt.isoformat()}"
    )
    mock_log.info.assert_called_once()


@patch("offkai_bot.alerts.alerts._log")
def test_register_alert_aware_datetime_jst(mock_log, mock_task):
    """Test registering an alert with an aware JST datetime."""
    # Arrange
    aware_jst_dt = datetime(3024, 8, 15, 10, 30, 0, tzinfo=JST)  # Already JST
    expected_key = aware_jst_dt.strftime(alerts._TIME_KEY_FORMAT)

    # Act
    alerts.register_alert(aware_jst_dt, mock_task)

    # Assert
    assert expected_key in alerts._scheduled_tasks
    assert alerts._scheduled_tasks[expected_key] == [mock_task]
    # Check that the conversion log shows JST -> JST
    mock_log.debug.assert_called_once_with(
        f"Registering alert: Aware time {aware_jst_dt.isoformat()} converted to JST -> {aware_jst_dt.isoformat()}"
    )
    mock_log.info.assert_called_once()


@patch("offkai_bot.alerts.alerts._log")
def test_register_alert_in_past(mock_log, mock_task):
    """Test registering an alert set in the past."""
    # Arrange
    aware_jst_dt = datetime(2024, 8, 15, 10, 30, 0, tzinfo=JST)  # Already JST
    expected_key = aware_jst_dt.strftime(alerts._TIME_KEY_FORMAT)

    # Act
    with pytest.raises(alerts.AlertTimeInPastError):
        # Should raise AlertTimeInPastError
        alerts.register_alert(aware_jst_dt, mock_task)

    # Assert
    assert expected_key not in alerts._scheduled_tasks
    # Check that the conversion log shows JST -> JST
    mock_log.debug.assert_called_once()
    mock_log.warning.assert_called_once()


@patch("offkai_bot.alerts.alerts._log")
def test_register_alert_multiple_tasks_same_time(mock_log):
    """Test registering multiple tasks for the exact same minute."""
    # Arrange
    alert_dt = datetime(3024, 8, 15, 11, 0, 0, tzinfo=JST)
    expected_key = alert_dt.strftime(alerts._TIME_KEY_FORMAT)
    task1 = MagicMock(spec=Task)
    task1.__class__.__name__ = "Task1"
    task2 = MagicMock(spec=Task)
    task2.__class__.__name__ = "Task2"

    # Act
    alerts.register_alert(alert_dt, task1)
    alerts.register_alert(alert_dt, task2)  # Register second task for same time

    # Assert
    assert expected_key in alerts._scheduled_tasks
    assert len(alerts._scheduled_tasks[expected_key]) == 2
    assert task1 in alerts._scheduled_tasks[expected_key]
    assert task2 in alerts._scheduled_tasks[expected_key]
    # Check logs (ensure info log called twice)
    assert mock_log.info.call_count == 2


@patch("offkai_bot.alerts.alerts._log")
def test_register_alert_ignores_seconds(mock_log):
    """Test that register_alert groups tasks with different seconds within the same minute."""
    # Arrange
    time1 = datetime(3024, 8, 15, 11, 5, 15, tzinfo=JST)  # 11:05:15
    time2 = datetime(3024, 8, 15, 11, 5, 45, tzinfo=JST)  # 11:05:45

    # Expected key ignores seconds
    expected_key = time1.strftime(alerts._TIME_KEY_FORMAT)  # Should be "2024-08-15T11:05"
    assert expected_key == time2.strftime(alerts._TIME_KEY_FORMAT)  # Verify key generation is same

    task1 = MagicMock(spec=Task)
    task1.__class__.__name__ = "TaskSeconds15"
    task2 = MagicMock(spec=Task)
    task2.__class__.__name__ = "TaskSeconds45"

    # Act
    alerts.register_alert(time1, task1)
    alerts.register_alert(time2, task2)

    # Assert
    assert expected_key in alerts._scheduled_tasks
    assert len(alerts._scheduled_tasks[expected_key]) == 2
    assert task1 in alerts._scheduled_tasks[expected_key]
    assert task2 in alerts._scheduled_tasks[expected_key]
    # Check logs
    assert mock_log.info.call_count == 2


@patch("offkai_bot.alerts.alerts.register_alert")  # <-- CORRECTED PATCH PATH
@patch("offkai_bot.event_actions._log")
def test_register_deadline_reminders_success(mock_log, mock_register_alert, mock_client, mock_thread, future_event):
    """Test registering all reminders and close task for an event with future deadline and channel ID."""
    # Arrange
    event = future_event
    deadline = event.event_deadline
    assert deadline is not None  # Ensure deadline exists for type checking
    expected_close_time = deadline
    expected_1d_time = deadline - timedelta(days=1)
    expected_3d_time = deadline - timedelta(days=3)
    expected_7d_time = deadline - timedelta(days=7)

    # Act
    register_deadline_reminders(mock_client, event, mock_thread)

    # Assert
    assert mock_register_alert.call_count == 4
    mock_log.info.assert_any_call(f"Registering deadline reminders for event '{event.event_name}'.")

    # Check Close Task registration
    mock_register_alert.assert_any_call(
        expected_close_time, CloseOffkaiTask(client=mock_client, event_name=event.event_name)
    )
    mock_log.info.assert_any_call(f"Registered auto-close task for '{event.event_name}'.")

    # Check 1 Day Reminder registration
    mock_register_alert.assert_any_call(
        expected_1d_time,
        SendMessageTask(
            client=mock_client,
            channel_id=event.channel_id,
            message=ANY,
        ),
    )
    mock_log.info.assert_any_call(f"Registered 24 hour reminder for '{event.event_name}'.")

    # Check 3 Day Reminder registration
    mock_register_alert.assert_any_call(
        expected_3d_time,
        SendMessageTask(
            client=mock_client,
            channel_id=event.channel_id,
            message=ANY,
        ),
    )
    mock_log.info.assert_any_call(f"Registered 3 day reminder for '{event.event_name}'.")

    # Check 7 Day Reminder registration
    mock_register_alert.assert_any_call(
        expected_7d_time,
        SendMessageTask(
            client=mock_client,
            channel_id=event.channel_id,
            message=ANY,
        ),
    )
    mock_log.info.assert_any_call(f"Registered 1 week reminder for '{event.event_name}'.")


@patch("offkai_bot.alerts.alerts.register_alert")
@patch("offkai_bot.event_actions._log")
def test_register_deadline_reminders_with_ping_role(
    mock_log, mock_register_alert, mock_client, mock_thread, future_event
):
    """Test that reminder messages include role ping when ping_role_id is set."""
    # Arrange
    event = future_event
    event.ping_role_id = 99887766

    # Act
    register_deadline_reminders(mock_client, event, mock_thread)

    # Assert - check that SendMessageTask messages include the role ping
    assert mock_register_alert.call_count == 4
    role_ping_prefix = "<@&99887766> "

    # Extract the SendMessageTask calls (skip the first CloseOffkaiTask call)
    send_msg_calls = [call for call in mock_register_alert.call_args_list if isinstance(call[0][1], SendMessageTask)]
    assert len(send_msg_calls) == 3

    for call in send_msg_calls:
        task = call[0][1]
        assert task.message.startswith(role_ping_prefix), (
            f"Expected message to start with role ping, got: {task.message}"
        )


@patch("offkai_bot.alerts.alerts.register_alert")
@patch("offkai_bot.event_actions._log")
def test_register_deadline_reminders_without_ping_role(
    mock_log, mock_register_alert, mock_client, mock_thread, future_event
):
    """Test that reminder messages do NOT include role ping when ping_role_id is None."""
    # Arrange
    event = future_event
    assert event.ping_role_id is None  # Default is None

    # Act
    register_deadline_reminders(mock_client, event, mock_thread)

    # Assert - check that SendMessageTask messages do NOT include any role ping
    send_msg_calls = [call for call in mock_register_alert.call_args_list if isinstance(call[0][1], SendMessageTask)]
    assert len(send_msg_calls) == 3

    for call in send_msg_calls:
        task = call[0][1]
        assert not task.message.startswith("<@&"), f"Expected no role ping, got: {task.message}"


@patch("offkai_bot.alerts.alerts.register_alert")  # <-- CORRECTED PATCH PATH
@patch("offkai_bot.event_actions._log")
def test_register_deadline_reminders_no_channel_id(
    mock_log, mock_register_alert, mock_client, mock_thread, future_event
):
    """Test registering only the close task when channel_id is missing."""
    # Arrange
    event = future_event
    event.channel_id = None  # Remove channel ID
    deadline = event.event_deadline
    assert deadline is not None
    expected_close_time = deadline

    # Act
    register_deadline_reminders(mock_client, event, mock_thread)

    # Assert
    # Only the close task should be registered
    assert mock_register_alert.call_count == 1
    mock_log.info.assert_any_call(f"Registering deadline reminders for event '{event.event_name}'.")

    # Check Close Task registration
    mock_register_alert.assert_called_once_with(
        expected_close_time, CloseOffkaiTask(client=mock_client, event_name=event.event_name)
    )
    mock_log.info.assert_any_call(f"Registered auto-close task for '{event.event_name}'.")

    # Ensure reminder logs were NOT called
    assert mock_log.info.call_count == 2  # Registering + Close Task


@patch("offkai_bot.alerts.alerts.register_alert")  # <-- CORRECTED PATCH PATH
@patch("offkai_bot.event_actions._log")
def test_register_deadline_reminders_no_deadline(mock_log, mock_register_alert, mock_client, mock_thread, future_event):
    """Test that no alerts are registered if the event has no deadline."""
    # Arrange
    event = future_event
    event.event_deadline = None  # Remove deadline

    # Act
    register_deadline_reminders(mock_client, event, mock_thread)

    # Assert
    mock_register_alert.assert_not_called()
    mock_log.info.assert_called_once_with(f"Registering deadline reminders for event '{event.event_name}'.")
    # Ensure no other info logs were generated
    assert mock_log.info.call_count == 1


@patch("offkai_bot.alerts.alerts.register_alert")  # <-- CORRECTED PATCH PATH
@patch("offkai_bot.event_actions._log")
def test_register_deadline_reminders_past_reminders_suppressed(
    mock_log, mock_register_alert, mock_client, mock_thread, future_event
):
    """Test that reminders for times already past are suppressed and not registered."""
    # Arrange
    event = future_event
    now_utc = datetime.now(UTC)
    # Set deadline only 2 days in the future
    deadline_utc = now_utc + timedelta(days=2)
    event.event_deadline = deadline_utc
    event.event_datetime = deadline_utc + timedelta(days=1)  # Event still after deadline

    expected_close_time = deadline_utc
    expected_1d_time = deadline_utc - timedelta(days=1)
    # 3d and 7d reminders would be in the past relative to 'now_utc'

    # Simulate register_alert raising AlertTimeInPastError for past times
    def register_alert_side_effect(alert_time, task):
        if alert_time <= now_utc:
            raise AlertTimeInPastError(alert_time)
        # Otherwise, do nothing (mock call is recorded)

    mock_register_alert.side_effect = register_alert_side_effect

    # Act
    register_deadline_reminders(mock_client, event, mock_thread)

    # Assert
    # Close task and 1d reminder should be registered
    assert mock_register_alert.call_count == 3
    mock_log.info.assert_any_call(f"Registering deadline reminders for event '{event.event_name}'.")

    # Check Close Task registration
    mock_register_alert.assert_any_call(
        expected_close_time, CloseOffkaiTask(client=mock_client, event_name=event.event_name)
    )
    mock_log.info.assert_any_call(f"Registered auto-close task for '{event.event_name}'.")

    # Check 1 Day Reminder registration
    mock_register_alert.assert_any_call(
        expected_1d_time,
        SendMessageTask(
            client=mock_client,
            channel_id=event.channel_id,
            message=ANY,
        ),
    )
    mock_log.info.assert_any_call(ANY)
