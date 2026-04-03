# src/offkai_bot/util.py
import functools
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import discord
from dateparser.date import DateDataParser  # type: ignore[import-untyped]

# Use relative imports for sibling modules within the package
from offkai_bot.errors import (
    EventDateTimeInPastError,
    EventDeadlineAfterEventError,
    EventDeadlineInPastError,
    InvalidChannelTypeError,
    InvalidDateTimeFormatError,
)

_log = logging.getLogger(__name__)
# --- Define JST using zoneinfo (preferred) ---

JST = ZoneInfo("Asia/Tokyo")
_log.info("Using ZoneInfo for JST timezone.")

_DATEPARSER_SETTINGS = {
    "TIMEZONE": "Asia/Tokyo",
    "TO_TIMEZONE": "UTC",
    "RETURN_AS_TIMEZONE_AWARE": True,
    "PREFER_DATES_FROM": "future",
}
_DATE_TIME_EXAMPLE_TEXT = "a date and time, for example '2024-08-15 19:30' or 'tomorrow 7pm'"


# --- Parsing/Validation Helpers ---


def parse_event_datetime(date_time_str: str) -> datetime:
    """
    Parses a free-form date/time string or raises InvalidDateTimeFormatError.
    IMPORTANT: Assumes the parsed datetime should be treated as JST and converts to UTC.
    """
    normalized_input = date_time_str.strip()
    if not normalized_input:
        raise InvalidDateTimeFormatError(_DATE_TIME_EXAMPLE_TEXT)

    parser = DateDataParser(settings={**_DATEPARSER_SETTINGS, "RELATIVE_BASE": datetime.now(JST)})
    parsed_data = parser.get_date_data(normalized_input)
    parsed_datetime = parsed_data.date_obj
    if parsed_datetime is None:
        raise InvalidDateTimeFormatError(_DATE_TIME_EXAMPLE_TEXT)

    utc_dt = parsed_datetime.astimezone(UTC)
    _log.debug("Parsed '%s' (assumed JST) to UTC: %s", normalized_input, utc_dt)
    return utc_dt


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
        _log.info("Validation failed: Event datetime %s is in the past compared to %s.", event_datetime, now_utc)
        raise EventDateTimeInPastError()
    _log.debug("Validation success: Event datetime %s is in the future.", event_datetime)


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
        _log.info("Validation failed: Deadline %s is in the past compared to %s.", event_deadline, now_utc)
        raise EventDeadlineInPastError()

    # 2. Check if deadline is before event time
    if event_deadline >= event_datetime:
        _log.info("Validation failed: Deadline %s is not before event time %s.", event_deadline, event_datetime)
        raise EventDeadlineAfterEventError()

    _log.debug(
        "Validation success: Deadline %s is in the future and before event time %s.",
        event_deadline,
        event_datetime,
    )


def log_command_usage(func):
    """
    Decorator to log command usage.
    Logs the user, command name, and arguments.
    """

    @functools.wraps(func)
    async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
        user = interaction.user
        command_name = interaction.command.name if interaction.command else func.__name__
        _log.info(
            "User '%s' (ID: %s) invoked command '%s' in channel '%s'",
            user,
            user.id,
            command_name,
            interaction.channel,
        )
        _log.debug("Arguments: args=%s, kwargs=%s", args, kwargs)
        return await func(self, interaction, *args, **kwargs)

    return wrapper
