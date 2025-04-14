# src/offkai_bot/util.py
import logging
from datetime import datetime

import discord

# Use relative imports for sibling modules within the package
from .errors import (
    InvalidChannelTypeError,
    InvalidDateTimeFormatError,
)

_log = logging.getLogger(__name__)


# --- Parsing/Validation Helpers ---


def parse_event_datetime(date_time_str: str) -> datetime:
    """Parses the date string or raises InvalidDateTimeFormatError."""
    try:
        # Add timezone logic here if needed later
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


# --- REMOVED CODE ---
# - DataclassJSONEncoder (moved to data.encoders)
# - EVENT_DATA_CACHE, RESPONSE_DATA_CACHE (moved to data.event, data.response)
# - _load_event_data, load_event_data, save_event_data, get_event (moved to data.event)
# - _load_responses, load_responses, save_responses, get_responses, add_response, remove_response (moved to data.response)
