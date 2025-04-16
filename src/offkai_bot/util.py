# src/offkai_bot/util.py
import logging
from datetime import UTC, datetime, timedelta, timezone

import discord

# Use relative imports for sibling modules within the package
from .errors import (
    EventDateTimeInPastError,
    EventDeadlineAfterEventError,
    EventDeadlineInPastError,
    InvalidChannelTypeError,
    InvalidDateTimeFormatError,
)

_log = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9), name="JST")  # Use this for conversion


# --- Parsing/Validation Helpers ---


def parse_event_datetime(date_time_str: str) -> datetime:
    """
    Parses the date string or raises InvalidDateTimeFormatError.
    IMPORTANT: Assumes the parsed datetime should be treated as JST and converts to UTC.
    """
    try:
        naive_dt = datetime.strptime(date_time_str, r"%Y-%m-%d %H:%M")
        # Assume input is JST, make aware, convert to UTC
        aware_jst = naive_dt.replace(tzinfo=JST)  # Assuming JST is accessible or defined here/imported
        utc_dt = aware_jst.astimezone(UTC)
        _log.debug(f"Parsed '{date_time_str}' (assumed JST) to UTC: {utc_dt}")
        return utc_dt
    except ValueError:
        raise InvalidDateTimeFormatError()
    except NameError:  # Fallback if event_data.JST isn't easily available here
        _log.error("JST timezone constant not found for parsing. Returning naive datetime.")
        # This path is less ideal as it breaks UTC consistency.
        # Consider defining JST within util.py or ensuring it's passed/imported.
        try:
            return datetime.strptime(date_time_str, r"%Y-%m-%d %H:%M")
        except ValueError:
            raise InvalidDateTimeFormatError()


def parse_drinks(drinks_str: str | None) -> list[str]:
    """Parses the comma-separated drinks string."""
    if not drinks_str:
        return []
    return [d.strip() for d in drinks_str.split(",") if d.strip()]


def validate_interaction_context(interaction: discord.Interaction):
    """Checks if the command is used in a valid guild text channel."""
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        raise InvalidChannelTypeError()


# --- NEW DATETIME VALIDATION FUNCTIONS ---


def validate_event_datetime(event_datetime: datetime):
    """
    Validates that the event datetime is set in the future (compared to current UTC).

    Raises:
        EventDateTimeInPastError: If the event_datetime is not in the future.
    """
    now_utc = datetime.now(UTC)
    if event_datetime <= now_utc:
        _log.info(f"Validation failed: Event datetime {event_datetime} is in the past compared to {now_utc}.")
        raise EventDateTimeInPastError()
    _log.debug(f"Validation success: Event datetime {event_datetime} is in the future.")


def validate_event_deadline(event_datetime: datetime, event_deadline: datetime | None):
    """
    Validates that the event deadline is set in the future (compared to current UTC)
    and occurs before the event datetime. If event deadline is None, then no validation is done.

    Args:
        event_datetime: The aware UTC datetime of the event.
        event_deadline: The aware UTC datetime of the deadline. Can be None.

    Raises:
        DeadlineInPastError: If the event_deadline is not in the future.
        DeadlineAfterEventError: If the event_deadline is not before the event_datetime.
    """
    if not event_deadline:
        return

    now_utc = datetime.now(UTC)

    # 1. Check if deadline is in the future
    if event_deadline < now_utc:
        _log.info(f"Validation failed: Deadline {event_deadline} is in the past compared to {now_utc}.")
        raise EventDeadlineInPastError()

    # 2. Check if deadline is before event time
    if event_deadline >= event_datetime:
        _log.info(f"Validation failed: Deadline {event_deadline} is not before event time {event_datetime}.")
        raise EventDeadlineAfterEventError()

    _log.debug(
        f"Validation success: Deadline {event_deadline} is in the future and before event time {event_datetime}."
    )
