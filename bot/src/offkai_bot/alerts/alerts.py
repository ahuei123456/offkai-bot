# src/offkai_bot/alerts/alerts.py
import logging
from collections.abc import Callable
from datetime import datetime

import discord
from discord.ext import tasks  # type: ignore[attr-defined]

# Import necessary components from your project
from offkai_bot.alerts.task import Task
from offkai_bot.errors import AlertTimeInPastError
from offkai_bot.util import JST  # Import JST from util

_log = logging.getLogger(__name__)

# --- Storage for Scheduled Tasks ---
_scheduled_tasks: dict[str, list[Task]] = {}

# Client the loop waits on before its first tick; set by start_alert_loop().
_client: discord.Client | None = None

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
        _log.debug("Registering alert: Naive time %s assumed JST -> %s", alert_time, alert_time_jst.isoformat())
    else:
        alert_time_jst = alert_time.astimezone(JST)
        _log.debug(
            "Registering alert: Aware time %s converted to JST -> %s",
            alert_time.isoformat(),
            alert_time_jst.isoformat(),
        )

    now_jst = datetime.now(JST)
    # Compare aware datetimes directly
    if alert_time_jst <= now_jst:
        _log.warning(
            "Attempted to register alert for past time: %s (Now: %s)",
            alert_time_jst.isoformat(),
            now_jst.isoformat(),
        )
        raise AlertTimeInPastError(alert_time_jst)

    # --- Generate Key ---
    key = alert_time_jst.strftime(_TIME_KEY_FORMAT)

    # --- Add to Storage ---
    _scheduled_tasks.setdefault(key, []).append(task)
    _log.info("Registered task %s for time key: %s", type(task).__name__, key)


def clear_alerts():
    global _scheduled_tasks

    _scheduled_tasks.clear()
    _log.info("Cleared all scheduled alerts.")


def remove_alerts(predicate: Callable[[Task], bool]) -> int:
    """Removes every scheduled task matching ``predicate`` and drops any now-empty
    time buckets. Returns the number of tasks removed."""
    global _scheduled_tasks

    removed = 0
    for key in list(_scheduled_tasks.keys()):
        kept = [task for task in _scheduled_tasks[key] if not predicate(task)]
        removed += len(_scheduled_tasks[key]) - len(kept)
        if kept:
            _scheduled_tasks[key] = kept
        else:
            del _scheduled_tasks[key]

    if removed:
        _log.info("Removed %s scheduled task(s) matching predicate.", removed)
    return removed


# --- Helper function processes tasks based on a given time ---
async def fire_alert(current_time: datetime):
    """
    Executes and removes every scheduled task whose time key is at or before
    current_time. Sweeping all due keys (rather than exact-matching the current
    minute) means a loop tick that fires late or skips a minute catches up on
    missed alerts instead of silently dropping them.

    Args:
        current_time: The timezone-aware datetime object (expected to be JST)
                      representing the current time to check for tasks.
    """
    global _scheduled_tasks

    # --- Generate Key from the provided time ---
    now_key = current_time.strftime(_TIME_KEY_FORMAT)
    _log.debug("Processing tasks for time key (JST): %s", now_key)

    # Keys in _TIME_KEY_FORMAT sort lexicographically in chronological order,
    # so a plain string comparison finds everything due.
    due_keys = sorted(key for key in _scheduled_tasks if key <= now_key)

    if not due_keys:
        _log.debug("No tasks scheduled for %s.", now_key)
        return  # Nothing due

    for key in due_keys:
        # Pop the bucket before executing so a task that mutates the schedule
        # (or a concurrent sweep) can't double-fire it.
        tasks_to_process = _scheduled_tasks.pop(key, None)
        if not tasks_to_process:
            continue

        _log.info("Found %s tasks scheduled for %s. Executing...", len(tasks_to_process), key)

        # --- Execute Tasks ---
        for task in tasks_to_process:
            # Ensure the task has the client instance if it needs it
            if not hasattr(task, "client") or task.client is None:
                _log.warning("Task %s for %s is missing client instance. Skipping.", type(task).__name__, key)
                continue

            try:
                _log.debug("Executing task: %s (%s)", type(task).__name__, getattr(task, "event_name", "N/A"))
                await task.action()
            except Exception as task_exec_err:
                # Log errors during the execution of a specific task's action
                _log.exception("Error executing task %s for key %s: %s", type(task).__name__, key, task_exec_err)

        _log.info("Removed %s executed tasks for key %s.", len(tasks_to_process), key)


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
        _log.exception("Error occurred within the main alert_loop cycle: %s", loop_err)


@alert_loop.before_loop
async def before_alert_loop():
    _log.info("Alert loop starting...")
    # Don't tick until the gateway is connected and the cache is populated —
    # otherwise tasks resolve channels/users to None and alerts are consumed
    # without ever being delivered.
    if _client is not None:
        await _client.wait_until_ready()


def start_alert_loop(client: discord.Client):
    """Starts the alert loop, holding onto the client so the loop can wait for
    the gateway to be ready before its first tick."""
    global _client
    _client = client
    alert_loop.start()


# Optional error handler for the loop task itself
# @alert_loop.error
# async def alert_loop_error(error):
#     _log.exception(f"Unhandled error in alert_loop task: {error}")
