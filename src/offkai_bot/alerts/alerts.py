# src/offkai_bot/alerts/alerts.py
import logging
from datetime import datetime

from discord.ext import tasks

from offkai_bot.errors import AlertTimeInPastError

from ..util import JST  # Import JST from util

# Import necessary components from your project
from .task import Task

_log = logging.getLogger(__name__)

# --- Storage for Scheduled Tasks ---
_scheduled_tasks: dict[str, list[Task]] = {}

# --- Key Format String ---
_TIME_KEY_FORMAT = "%Y-%m-%dT%H:%M"


def register_alert(alert_time: datetime, task: Task):
    """
    Registers a Task to be executed at a specific time.

    Args:
        alert_time: The datetime when the task should run.
                    If naive, it's assumed to be in JST.
        task: The Task object to execute.
    """
    global _scheduled_tasks

    # --- Timezone Handling ---
    if alert_time.tzinfo is None:
        alert_time_jst = alert_time.replace(tzinfo=JST)
        _log.debug(f"Registering alert: Naive time {alert_time} assumed JST -> {alert_time_jst.isoformat()}")
    else:
        alert_time_jst = alert_time.astimezone(JST)
        _log.debug(
            f"Registering alert: Aware time {alert_time.isoformat()} converted to JST -> {alert_time_jst.isoformat()}"
        )

    now_jst = datetime.now(JST)
    # Compare aware datetimes directly
    if alert_time_jst <= now_jst:
        _log.warning(
            f"Attempted to register alert for past time: {alert_time_jst.isoformat()} (Now: {now_jst.isoformat()})"
        )
        raise AlertTimeInPastError(alert_time_jst)

    # --- Generate Key ---
    key = alert_time_jst.strftime(_TIME_KEY_FORMAT)

    # --- Add to Storage ---
    _scheduled_tasks.setdefault(key, []).append(task)
    _log.info(f"Registered task {type(task).__name__} for time key: {key}")


def clear_alerts():
    global _scheduled_tasks

    _scheduled_tasks.clear()
    _log.info("Cleared all scheduled alerts.")


# --- NEW: Helper function processes tasks based on a given time ---
async def fire_alert(current_time: datetime):
    """
    Calculates the time key for the given current_time, looks up tasks,
    executes them, and removes them from the schedule.

    Args:
        current_time: The timezone-aware datetime object (expected to be JST)
                      representing the current time to check for tasks.
        client: The discord client instance.
    """
    global _scheduled_tasks

    # --- Generate Key from the provided time ---
    key = current_time.strftime(_TIME_KEY_FORMAT)
    _log.debug(f"Processing tasks for time key (JST): {key}")

    # --- Check for Tasks Scheduled for this specific time key ---
    tasks_to_process = _scheduled_tasks.get(key)

    if not tasks_to_process:
        _log.debug(f"No tasks scheduled for {key}.")
        return  # Nothing to do for this key

    _log.info(f"Found {len(tasks_to_process)} tasks scheduled for {key}. Executing...")

    # --- Execute Tasks ---
    for task in tasks_to_process:
        # Ensure the task has the client instance if it needs it
        if not hasattr(task, "client") or task.client is None:
            _log.warning(f"Task {type(task).__name__} for {key} is missing client instance. Skipping.")
            continue

        try:
            _log.debug(f"Executing task: {type(task).__name__} ({getattr(task, 'event_name', 'N/A')})")
            await task.action()
        except Exception as task_exec_err:
            # Log errors during the execution of a specific task's action
            _log.exception(f"Error executing task {type(task).__name__} for key {key}: {task_exec_err}")

    # --- Remove Executed Tasks ---
    # Remove the key from the dictionary after processing all tasks for that minute
    removed_tasks_list = _scheduled_tasks.pop(key, None)
    if removed_tasks_list:
        _log.info(f"Removed {len(removed_tasks_list)} executed tasks for key {key}.")
    else:
        _log.warning(f"Attempted to remove tasks for key {key}, but key was not found (potentially already removed).")


# --- Refactored alert_loop ---
@tasks.loop(minutes=1.0)
async def alert_loop():
    """
    Gets the current time each minute and calls the helper function
    to process any tasks scheduled for that time.
    """
    try:
        # Get current time in JST
        current_time_jst = datetime.now(JST)

        # --- Delegate processing to the helper function, passing the current time ---
        await fire_alert(current_time_jst)
        # --- End Delegation ---

    except Exception as loop_err:
        # Catch broad exceptions during time calculation or helper call initiation
        # to ensure the loop itself continues running next minute.
        _log.exception(f"Error occurred within the main alert_loop cycle: {loop_err}")


@alert_loop.before_loop
async def before_alert_loop():
    _log.info("Alert loop starting...")
    # Rely on setup_hook finishing before the loop starts naturally.


# Optional error handler for the loop task itself
# @alert_loop.error
# async def alert_loop_error(error):
#     _log.exception(f"Unhandled error in alert_loop task: {error}")
