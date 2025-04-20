# tests/alerts/test_alerts.py

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

# Import the module and functions to test
from offkai_bot.alerts import alerts
from offkai_bot.alerts.task import Task  # Import base Task for type hinting
from offkai_bot.util import JST  # Import the JST timezone object

# pytest marker for async tests
pytestmark = pytest.mark.asyncio

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


# --- Tests for fire_alert ---


@patch("offkai_bot.alerts.alerts._log")
async def test_fire_alert_no_tasks_scheduled(mock_log):
    """Test fire_alert when no tasks are scheduled for the given time."""
    # Arrange
    current_time = datetime(3024, 8, 15, 12, 0, 0, tzinfo=JST)
    current_key = current_time.strftime(alerts._TIME_KEY_FORMAT)
    # Ensure _scheduled_tasks is empty (handled by fixture)

    # Act
    await alerts.fire_alert(current_time)

    # Assert
    assert not alerts._scheduled_tasks  # Should remain empty
    mock_log.debug.assert_any_call(f"Processing tasks for time key (JST): {current_key}")
    mock_log.debug.assert_any_call(f"No tasks scheduled for {current_key}.")
    mock_log.info.assert_not_called()  # No tasks found/executed


@patch("offkai_bot.alerts.alerts._log")
async def test_fire_alert_task_exists_success(mock_log, mock_task):
    """Test fire_alert executes a scheduled task successfully."""
    # Arrange
    current_time = datetime(3024, 8, 15, 12, 5, 0, tzinfo=JST)
    current_key = current_time.strftime(alerts._TIME_KEY_FORMAT)
    # Manually schedule the task
    alerts._scheduled_tasks[current_key] = [mock_task]

    # Act
    await alerts.fire_alert(current_time)

    # Assert
    # 1. Task action was called
    mock_task.action.assert_awaited_once()
    # 3. Task was removed from schedule
    assert current_key not in alerts._scheduled_tasks
    # 4. Check logs
    mock_log.debug.assert_called()
    mock_log.info.assert_called()


@patch("offkai_bot.alerts.alerts._log")
async def test_fire_alert_multiple_tasks_success(mock_log, mock_client):
    """Test fire_alert executes multiple scheduled tasks successfully."""
    # Arrange
    current_time = datetime(3024, 8, 15, 12, 10, 0, tzinfo=JST)
    current_key = current_time.strftime(alerts._TIME_KEY_FORMAT)
    task1 = MagicMock(spec=Task, client=mock_client)
    task1.action = AsyncMock()
    task1.__class__.__name__ = "Task1"
    task2 = MagicMock(spec=Task, client=mock_client)
    task2.action = AsyncMock()
    task2.__class__.__name__ = "Task2"
    alerts._scheduled_tasks[current_key] = [task1, task2]

    # Act
    await alerts.fire_alert(current_time)

    # Assert
    task1.action.assert_awaited_once()
    task2.action.assert_awaited_once()
    assert current_key not in alerts._scheduled_tasks
    mock_log.info.assert_called()
    assert mock_log.debug.call_count >= 3  # Processing key + 2 executions


@patch("offkai_bot.alerts.alerts._log")
async def test_fire_alert_task_action_fails(mock_log, mock_task):
    """Test fire_alert handles exceptions raised by a task's action method."""
    # Arrange
    current_time = datetime(3024, 8, 15, 12, 15, 0, tzinfo=JST)
    current_key = current_time.strftime(alerts._TIME_KEY_FORMAT)
    error_message = "Task failed!"
    mock_task.action.side_effect = Exception(error_message)
    alerts._scheduled_tasks[current_key] = [mock_task]

    # Act
    await alerts.fire_alert(current_time)

    # Assert
    # 1. Task action was still called (attempted)
    mock_task.action.assert_awaited_once()
    # 2. Task was still removed from schedule
    assert current_key not in alerts._scheduled_tasks
    # 3. Exception was logged
    mock_log.exception.assert_called_once()
    # 4. Info log still shows task was found/removed
    mock_log.info.assert_called()


@patch("offkai_bot.alerts.alerts._log")
async def test_fire_alert_task_no_client(mock_log, mock_client):
    """Test fire_alert handles tasks where there is no client."""
    # Arrange
    current_time = datetime(3024, 8, 15, 12, 20, 0, tzinfo=JST)
    current_key = current_time.strftime(alerts._TIME_KEY_FORMAT)

    # Create a mock task that will raise AttributeError on client assignment
    bad_task = MagicMock(spec=Task)
    bad_task.action = AsyncMock()
    bad_task.__class__.__name__ = "BadTask"
    # Simulate missing 'client' attribute or make it read-only
    del bad_task.client  # Ensure it doesn't exist

    alerts._scheduled_tasks[current_key] = [bad_task]

    # Act
    await alerts.fire_alert(current_time)

    # Assert
    # 1. Task action was NOT called
    bad_task.action.assert_not_awaited()
    # 2. Task was still removed from schedule
    assert current_key not in alerts._scheduled_tasks
    # 3. Check logs
    mock_log.warning.assert_called_once()
    mock_log.error.assert_not_called()
    mock_log.info.assert_called()
    mock_log.exception.assert_not_called()  # No exception expected here


@patch("offkai_bot.alerts.alerts._log")
async def test_fire_alert_triggers_on_different_seconds(mock_log, mock_client, mock_task):
    """Test fire_alert triggers tasks registered for a minute, even if called with different seconds."""
    # Arrange
    # Register task for 12:25:00 JST
    registration_time = datetime(3024, 8, 15, 12, 25, 0, tzinfo=JST)
    registration_key = registration_time.strftime(alerts._TIME_KEY_FORMAT)  # "2024-08-15T12:25"
    alerts.register_alert(registration_time, mock_task)

    # Time to trigger the alert loop check, within the same minute but different seconds
    fire_time = datetime(3024, 8, 15, 12, 25, 38, tzinfo=JST)  # 12:25:38 JST
    fire_key = fire_time.strftime(alerts._TIME_KEY_FORMAT)  # Should also be "2024-08-15T12:25"
    assert registration_key == fire_key  # Verify keys match

    # Act
    await alerts.fire_alert(fire_time)

    # Assert
    # 1. Task action was called
    mock_task.action.assert_awaited_once()
    # 2. Client was assigned
    assert mock_task.client == mock_client
    # 3. Task was removed using the correct key
    assert fire_key not in alerts._scheduled_tasks
    # 4. Check logs
    mock_log.info.assert_called()
    mock_log.debug.assert_called()
