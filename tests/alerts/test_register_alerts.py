# tests/alerts/test_alerts.py

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

# Import the module and functions to test
from offkai_bot.alerts import alerts
from offkai_bot.alerts.task import Task  # Import base Task for type hinting
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
