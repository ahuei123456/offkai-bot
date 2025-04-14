# tests/test_util.py

from datetime import datetime
from unittest.mock import MagicMock

import discord  # Import discord for type mocking
import pytest

from offkai_bot.errors import (
    InvalidChannelTypeError,
    InvalidDateTimeFormatError,
)

# Import functions and errors from the module under test
from offkai_bot.util import (
    parse_drinks,
    parse_event_datetime,
    validate_interaction_context,
)

# --- Tests for parse_event_datetime ---

def test_parse_event_datetime_success():
    """Test parsing a valid datetime string."""
    date_str = "2024-08-15 19:30"
    expected_dt = datetime(2024, 8, 15, 19, 30)
    assert parse_event_datetime(date_str) == expected_dt

@pytest.mark.parametrize(
    "invalid_str",
    [
        "2024-08-15",  # Missing time
        "19:30",  # Missing date
        "2024/08/15 19:30",  # Wrong separator
        "15-08-2024 19:30",  # Wrong date order
        "2024-08-15 7:30 PM",  # Wrong time format
        "invalid date string", # Completely wrong
        "", # Empty string
    ],
)
def test_parse_event_datetime_invalid_format(invalid_str):
    """Test parsing various invalid datetime string formats."""
    with pytest.raises(InvalidDateTimeFormatError):
        parse_event_datetime(invalid_str)

def test_parse_event_datetime_invalid_values():
    """Test parsing strings with valid format but invalid date/time values."""
    # datetime.strptime raises ValueError for these, which our function catches
    with pytest.raises(InvalidDateTimeFormatError):
        parse_event_datetime("2024-13-15 19:30")  # Invalid month
    with pytest.raises(InvalidDateTimeFormatError):
        parse_event_datetime("2024-08-32 19:30")  # Invalid day
    with pytest.raises(InvalidDateTimeFormatError):
        parse_event_datetime("2024-08-15 25:30")  # Invalid hour

# --- Tests for parse_drinks ---

@pytest.mark.parametrize(
    "input_str, expected_list",
    [
        (None, []),
        ("", []),
        ("Beer", ["Beer"]),
        ("Beer, Wine", ["Beer", "Wine"]),
        (" Beer , Wine,Soda ", ["Beer", "Wine", "Soda"]), # Test stripping whitespace
        ("Beer,,Wine,", ["Beer", "Wine"]), # Test empty entries
        (",,", []), # Test only separators
        ("   ", []), # Test only whitespace
    ],
)
def test_parse_drinks(input_str, expected_list):
    """Test parsing various drink strings."""
    assert parse_drinks(input_str) == expected_list

# --- Tests for validate_interaction_context ---

@pytest.fixture
def mock_interaction():
    """Fixture to create a mock discord.Interaction."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = None # Default to no guild (DM)
    interaction.channel = None # Default to no channel
    return interaction

def test_validate_interaction_context_success(mock_interaction):
    """Test validation succeeds in a guild text channel."""
    mock_interaction.guild = MagicMock(spec=discord.Guild)
    mock_interaction.channel = MagicMock(spec=discord.TextChannel)
    # Should not raise any error
    try:
        validate_interaction_context(mock_interaction)
    except InvalidChannelTypeError:
        pytest.fail("validate_interaction_context raised InvalidChannelTypeError unexpectedly")

def test_validate_interaction_context_no_guild(mock_interaction):
    """Test validation fails when interaction.guild is None (DM)."""
    mock_interaction.guild = None
    mock_interaction.channel = MagicMock(spec=discord.DMChannel) # Set a channel type for completeness
    with pytest.raises(InvalidChannelTypeError):
        validate_interaction_context(mock_interaction)

@pytest.mark.parametrize(
    "channel_type",
    [
        discord.DMChannel,
        discord.VoiceChannel,
        discord.Thread,
        discord.CategoryChannel,
        None, # Test None channel explicitly
    ]
)
def test_validate_interaction_context_wrong_channel_type(mock_interaction, channel_type):
    """Test validation fails with various non-TextChannel types."""
    mock_interaction.guild = MagicMock(spec=discord.Guild)
    # Set channel to a mock of the specified type, or None
    mock_interaction.channel = MagicMock(spec=channel_type) if channel_type else None

    with pytest.raises(InvalidChannelTypeError):
        validate_interaction_context(mock_interaction)

