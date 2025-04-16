# tests/test_util.py

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import discord  # Import discord for type mocking
import pytest

from offkai_bot.errors import (
    EventDateTimeInPastError,
    EventDeadlineAfterEventError,
    EventDeadlineInPastError,
    InvalidChannelTypeError,
    InvalidDateTimeFormatError,
)

# Import functions and errors from the module under test
from offkai_bot.util import (
    JST,
    parse_drinks,
    parse_event_datetime,
    validate_event_datetime,
    validate_event_deadline,
    validate_interaction_context,
)

# --- Tests for parse_event_datetime ---


def test_parse_event_datetime_success():
    """Test parsing a valid datetime string converts assumed JST to UTC."""
    date_str = "2024-08-15 19:30"  # Represents 19:30 JST

    # Calculate expected UTC time
    expected_naive = datetime(2024, 8, 15, 19, 30)
    expected_aware_jst = expected_naive.replace(tzinfo=JST)
    expected_utc = expected_aware_jst.astimezone(UTC)
    # expected_utc should be datetime(2024, 8, 15, 10, 30, tzinfo=UTC)

    # Patch the logger within the function's scope if needed, otherwise assume logging setup works
    with patch("offkai_bot.util._log") as mock_log:
        result = parse_event_datetime(date_str)
        assert result == expected_utc
        assert result.tzinfo is UTC  # Explicitly check timezone is UTC
        mock_log.debug.assert_called_once()  # Check logging occurred


@pytest.mark.parametrize(
    "invalid_str",
    [
        "2024-08-15",  # Missing time
        "19:30",  # Missing date
        "2024/08/15 19:30",  # Wrong separator
        "15-08-2024 19:30",  # Wrong date order
        "2024-08-15 7:30 PM",  # Wrong time format
        "invalid date string",  # Completely wrong
        "",  # Empty string
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
        (" Beer , Wine,Soda ", ["Beer", "Wine", "Soda"]),  # Test stripping whitespace
        ("Beer,,Wine,", ["Beer", "Wine"]),  # Test empty entries
        (",,", []),  # Test only separators
        ("   ", []),  # Test only whitespace
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
    interaction.guild = None  # Default to no guild (DM)
    interaction.channel = None  # Default to no channel
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
    mock_interaction.channel = MagicMock(spec=discord.DMChannel)  # Set a channel type for completeness
    with pytest.raises(InvalidChannelTypeError):
        validate_interaction_context(mock_interaction)


@pytest.mark.parametrize(
    "channel_type",
    [
        discord.DMChannel,
        discord.VoiceChannel,
        discord.Thread,
        discord.CategoryChannel,
        None,  # Test None channel explicitly
    ],
)
def test_validate_interaction_context_wrong_channel_type(mock_interaction, channel_type):
    """Test validation fails with various non-TextChannel types."""
    mock_interaction.guild = MagicMock(spec=discord.Guild)
    # Set channel to a mock of the specified type, or None
    mock_interaction.channel = MagicMock(spec=channel_type) if channel_type else None

    with pytest.raises(InvalidChannelTypeError):
        validate_interaction_context(mock_interaction)


# --- NEW Tests for validate_event_datetime ---


# Use patch to control 'now' for reliable testing near the boundary, though less critical here
@patch("offkai_bot.util.datetime")
def test_validate_event_datetime_future(mock_dt):
    """Test validation succeeds when event datetime is in the future."""
    now_utc = datetime(2024, 7, 20, 12, 0, 0, tzinfo=UTC)
    mock_dt.now.return_value = now_utc  # Control current time

    future_event_dt = now_utc + timedelta(days=1)

    try:
        validate_event_datetime(future_event_dt)
    except EventDateTimeInPastError:
        pytest.fail("validate_event_datetime raised EventDateTimeInPastError unexpectedly")
    mock_dt.now.assert_called_once_with(UTC)  # Verify UTC was requested


@patch("offkai_bot.util.datetime")
def test_validate_event_datetime_past(mock_dt):
    """Test validation fails when event datetime is in the past."""
    now_utc = datetime(2024, 7, 20, 12, 0, 0, tzinfo=UTC)
    mock_dt.now.return_value = now_utc  # Control current time

    past_event_dt = now_utc - timedelta(seconds=1)  # Just slightly in the past

    with pytest.raises(EventDateTimeInPastError):
        validate_event_datetime(past_event_dt)
    mock_dt.now.assert_called_once_with(UTC)


@patch("offkai_bot.util.datetime")
def test_validate_event_datetime_exactly_now(mock_dt):
    """Test validation fails when event datetime is exactly now (considered past)."""
    now_utc = datetime(2024, 7, 20, 12, 0, 0, tzinfo=UTC)
    mock_dt.now.return_value = now_utc  # Control current time

    event_dt_now = now_utc  # Exactly the same time

    with pytest.raises(EventDateTimeInPastError):
        validate_event_datetime(event_dt_now)
    mock_dt.now.assert_called_once_with(UTC)


# --- NEW Tests for validate_event_deadline ---

# Define some reference points for deadline tests
NOW_UTC_FOR_DEADLINE = datetime(2024, 7, 20, 12, 0, 0, tzinfo=UTC)
FUTURE_DEADLINE = NOW_UTC_FOR_DEADLINE + timedelta(days=5)  # July 25th
FUTURE_EVENT_AFTER_DEADLINE = FUTURE_DEADLINE + timedelta(days=10)  # Aug 4th
PAST_DEADLINE = NOW_UTC_FOR_DEADLINE - timedelta(days=1)  # July 19th
EVENT_BEFORE_DEADLINE = FUTURE_DEADLINE - timedelta(days=1)  # July 24th


@patch("offkai_bot.util.datetime")
def test_validate_event_deadline_success(mock_dt):
    """Test validation succeeds when deadline is future and before event."""
    mock_dt.now.return_value = NOW_UTC_FOR_DEADLINE

    try:
        validate_event_deadline(FUTURE_EVENT_AFTER_DEADLINE, FUTURE_DEADLINE)
    except (EventDeadlineInPastError, EventDeadlineAfterEventError):
        pytest.fail("validate_event_deadline raised an error unexpectedly")
    mock_dt.now.assert_called_once_with(UTC)


@patch("offkai_bot.util.datetime")
def test_validate_event_deadline_past(mock_dt):
    """Test validation fails when deadline is in the past."""
    mock_dt.now.return_value = NOW_UTC_FOR_DEADLINE

    with pytest.raises(EventDeadlineInPastError):
        validate_event_deadline(FUTURE_EVENT_AFTER_DEADLINE, PAST_DEADLINE)
    mock_dt.now.assert_called_once_with(UTC)


@patch("offkai_bot.util.datetime")
def test_validate_event_deadline_after_event(mock_dt):
    """Test validation fails when deadline is after the event time."""
    mock_dt.now.return_value = NOW_UTC_FOR_DEADLINE

    with pytest.raises(EventDeadlineAfterEventError):
        validate_event_deadline(EVENT_BEFORE_DEADLINE, FUTURE_DEADLINE)  # Deadline is after event
    mock_dt.now.assert_called_once_with(UTC)


@patch("offkai_bot.util.datetime")
def test_validate_event_deadline_equal_to_event(mock_dt):
    """Test validation fails when deadline is exactly the event time."""
    mock_dt.now.return_value = NOW_UTC_FOR_DEADLINE

    with pytest.raises(EventDeadlineAfterEventError):
        validate_event_deadline(FUTURE_DEADLINE, FUTURE_DEADLINE)  # Deadline == Event time
    mock_dt.now.assert_called_once_with(UTC)


@patch("offkai_bot.util.datetime")
def test_validate_event_deadline_past_error_takes_precedence(mock_dt):
    """Test that DeadlineInPastError is raised even if deadline is also after event."""
    mock_dt.now.return_value = NOW_UTC_FOR_DEADLINE

    # Deadline is both in the past AND technically after the (even further past) event time
    past_event_time = PAST_DEADLINE - timedelta(days=1)

    with pytest.raises(EventDeadlineInPastError):  # Expect the "past" error first
        validate_event_deadline(past_event_time, PAST_DEADLINE)
    mock_dt.now.assert_called_once_with(UTC)
