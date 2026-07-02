# tests/test_util.py

import base64
import hashlib
import hmac
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
# Import build_checkin_url / build_checkin_token for their own test sections below
from offkai_bot.util import (
    JST,
    build_checkin_token,
    build_checkin_url,
    generate_checkin_signature,
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


def test_parse_event_datetime_textual_date_success():
    """Test parsing a textual date format converts assumed JST to UTC."""
    date_str = "15 Aug 2024 19:30"

    expected_naive = datetime(2024, 8, 15, 19, 30)
    expected_aware_jst = expected_naive.replace(tzinfo=JST)
    expected_utc = expected_aware_jst.astimezone(UTC)

    with patch("offkai_bot.util._log") as mock_log:
        result = parse_event_datetime(date_str)
        assert result == expected_utc
        assert result.tzinfo is UTC
        mock_log.debug.assert_called_once()


@patch("offkai_bot.util.datetime")
def test_parse_event_datetime_relative_success(mock_dt):
    """Test parsing a relative date with an explicit time."""
    now_jst = datetime(2026, 3, 28, 12, 0, 0, tzinfo=JST)
    mock_dt.now.return_value = now_jst

    with patch("offkai_bot.util._log") as mock_log:
        result = parse_event_datetime("tomorrow 7pm")

    assert result == datetime(2026, 3, 29, 10, 0, 0, tzinfo=UTC)
    assert result.tzinfo is UTC
    mock_dt.now.assert_called_once_with(JST)
    mock_log.debug.assert_called_once()


@patch("offkai_bot.util.datetime")
def test_parse_event_datetime_relative_date_only_success(mock_dt):
    """Test parsing a relative date without an explicit time uses dateparser defaults."""
    now_jst = datetime(2026, 3, 28, 12, 0, 0, tzinfo=JST)
    mock_dt.now.return_value = now_jst

    with patch("offkai_bot.util._log") as mock_log:
        result = parse_event_datetime("tomorrow")

    assert result == datetime(2026, 3, 29, 3, 0, 0, tzinfo=UTC)
    assert result.tzinfo is UTC
    mock_dt.now.assert_called_once_with(JST)
    mock_log.debug.assert_called_once()


@pytest.mark.parametrize(
    "invalid_str",
    [
        "invalid date string",  # Completely wrong
        "7pm",  # Rejected by dateparser with the current parser settings
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


# --- Tests for generate_checkin_signature (legacy, event-less) ---


def test_generate_checkin_signature_matches_hmac():
    """Legacy signature is HMAC-SHA256(secret, str(user_id))[:16]."""
    expected = hmac.new(b"mykey", b"4242", hashlib.sha256).hexdigest()[:16]
    assert generate_checkin_signature(4242, "mykey") == expected


def test_generate_checkin_signature_empty_key_returns_empty():
    """No secret key → empty signature (keyless deployments)."""
    assert generate_checkin_signature(4242, "") == ""


# --- Tests for build_checkin_token (v2 event-bound) ---


def test_build_checkin_token_v2_format_and_signature():
    """v2 token is v2.<base64url(user_id:event_name)>.<16-char HMAC over payload>."""
    token = build_checkin_token(4242, "Summer Bash", "mykey")
    parts = token.split(".")
    assert len(parts) == 3
    assert parts[0] == "v2"

    payload, sig = parts[1], parts[2]
    # Payload has no '=' padding (URL-safe, matches the frontend verifier).
    assert "=" not in payload
    # Payload decodes back to the exact "user_id:event_name".
    decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
    assert decoded == "4242:Summer Bash"
    # Signature is HMAC-SHA256(secret, payload)[:16], matching token.ts.
    expected_sig = hmac.new(b"mykey", payload.encode(), hashlib.sha256).hexdigest()[:16]
    assert sig == expected_sig


def test_build_checkin_token_v2_preserves_large_discord_id():
    """An 18-digit Discord ID round-trips exactly (no JS-style precision loss)."""
    uid = 191524132624531458
    token = build_checkin_token(uid, "niji 8l tokyo d2", "k")
    payload = token.split(".")[1]
    decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
    assert decoded == f"{uid}:niji 8l tokyo d2"


# --- Tests for build_checkin_url ---


@patch("offkai_bot.util.get_config")
def test_build_checkin_url_no_frontend_url(mock_get_config):
    """Returns '' when FRONTEND_URL is not configured."""
    mock_get_config.return_value = {"FRONTEND_URL": "", "ADMIN_KEY": "secret"}
    assert build_checkin_url(42, "Summer Bash") == ""


@patch("offkai_bot.util.get_config")
def test_build_checkin_url_no_admin_key_returns_empty(mock_get_config):
    """Without ADMIN_KEY no URL is emitted (fail closed — a bare user_id token is forgeable)."""
    mock_get_config.return_value = {"FRONTEND_URL": "https://offkai.example", "ADMIN_KEY": ""}
    assert build_checkin_url(99, "Summer Bash") == ""


@patch("offkai_bot.util.get_config")
def test_build_checkin_url_with_admin_key_produces_v2_token(mock_get_config):
    """With ADMIN_KEY the URL carries the event-bound v2 token."""
    mock_get_config.return_value = {"FRONTEND_URL": "https://offkai.example", "ADMIN_KEY": "mykey"}
    result = build_checkin_url(4242, "Summer Bash")

    expected_token = build_checkin_token(4242, "Summer Bash", "mykey")
    assert result == f"https://offkai.example/?token={expected_token}"
    assert "/?token=v2." in result


@patch("offkai_bot.util.get_config")
def test_build_checkin_url_missing_keys_default_to_empty(mock_get_config):
    """Keys absent from config dict are treated as empty strings — no KeyError."""
    mock_get_config.return_value = {"FRONTEND_URL": "https://offkai.example"}
    result = build_checkin_url(7, "Summer Bash")
    # No ADMIN_KEY → fail closed, no URL.
    assert result == ""
