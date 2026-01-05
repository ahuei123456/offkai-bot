# tests/data/test_response.py
import json
from datetime import UTC, datetime
from unittest.mock import mock_open, patch

import pytest

# Import the module we are testing
from offkai_bot.data import response as response_data
from offkai_bot.data.encoders import DataclassJSONEncoder  # Needed for save verification
from offkai_bot.data.response import EventData, Response
from offkai_bot.errors import DuplicateResponseError, ResponseNotFoundError  # Import the dataclass too

# --- Test Data ---
NOW = datetime.now(UTC)
RESP_1_DICT = {
    "user_id": 123,
    "username": "User1",
    "extra_people": 1,
    "behavior_confirmed": True,
    "arrival_confirmed": True,
    "event_name": "Event A",
    "timestamp": NOW.isoformat(),
    "drinks": ["Cola"],
}
RESP_2_DICT = {
    "user_id": 456,
    "username": "User2",
    "extra_people": 0,
    "behavior_confirmed": "yes",
    "arrival_confirmed": "No",  # Test string bools
    "event_name": "Event A",
    "timestamp": NOW.isoformat(),
    "drinks": ["Water"],
}
RESP_3_DICT = {  # For a different event
    "user_id": 789,
    "username": "User3",
    "extra_people": 2,
    "behavior_confirmed": False,
    "arrival_confirmed": False,
    "event_name": "Event B",
    "timestamp": NOW.isoformat(),
    "drinks": [],
}
RESP_4_DICT = {  # Response with extras_names
    "user_id": 999,
    "username": "User4",
    "extra_people": 2,
    "behavior_confirmed": True,
    "arrival_confirmed": True,
    "event_name": "Event A",
    "timestamp": NOW.isoformat(),
    "drinks": ["Cola", "Water", "Juice"],
    "extras_names": ["Alice", "Bob"],
}

RESP_1_OBJ = Response(
    user_id=123,
    username="User1",
    extra_people=1,
    behavior_confirmed=True,
    arrival_confirmed=True,
    event_name="Event A",
    timestamp=NOW,
    drinks=["Cola"],
)
# Need to manually create obj 2 because of bool conversion logic
RESP_2_OBJ = Response(
    user_id=456,
    username="User2",
    extra_people=0,
    behavior_confirmed=True,
    arrival_confirmed=False,  # Note conversion
    event_name="Event A",
    timestamp=NOW,
    drinks=["Water"],
)
RESP_3_OBJ = Response(
    user_id=789,
    username="User3",
    extra_people=2,
    behavior_confirmed=False,
    arrival_confirmed=False,
    event_name="Event B",
    timestamp=NOW,
    drinks=[],
)
RESP_4_OBJ = Response(
    user_id=999,
    username="User4",
    extra_people=2,
    behavior_confirmed=True,
    arrival_confirmed=True,
    event_name="Event A",
    timestamp=NOW,
    drinks=["Cola", "Water", "Juice"],
    extras_names=["Alice", "Bob"],
)


# Old format (for migration tests)
OLD_FORMAT_RESPONSES_DICT = {"Event A": [RESP_1_DICT, RESP_2_DICT], "Event B": [RESP_3_DICT]}

# New format
VALID_RESPONSES_DICT = {
    "Event A": {"attendees": [RESP_1_DICT, RESP_2_DICT], "waitlist": []},
    "Event B": {"attendees": [RESP_3_DICT], "waitlist": []},
}
VALID_RESPONSES_JSON = json.dumps(VALID_RESPONSES_DICT, indent=4)
EMPTY_RESPONSES_JSON = json.dumps({}, indent=4)


# Helper to create EventData structure
def make_event_data(attendees=None, waitlist=None):
    """Helper to create EventData dict."""
    return EventData(attendees=attendees or [], waitlist=waitlist or [])


# --- Tests ---


# == _load_responses Tests ==


def test_load_responses_success(mock_paths):
    """Test loading valid response data from a file (new format)."""
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=VALID_RESPONSES_JSON)) as mock_file,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        mock_file.assert_called_once_with(mock_paths["responses"], "r", encoding="utf-8")
        assert "Event A" in responses
        assert "Event B" in responses
        assert "attendees" in responses["Event A"]
        assert "waitlist" in responses["Event A"]
        assert len(responses["Event A"]["attendees"]) == 2
        assert len(responses["Event B"]["attendees"]) == 1

        # Compare loaded objects carefully due to bool conversion
        assert responses["Event A"]["attendees"][0] == RESP_1_OBJ
        assert responses["Event A"]["attendees"][1] == RESP_2_OBJ
        assert responses["Event B"]["attendees"][0] == RESP_3_OBJ

        assert responses == response_data.RESPONSE_DATA_CACHE  # Check cache is set
        mock_log.warning.assert_not_called()
        mock_log.error.assert_not_called()


def test_load_responses_file_not_found(mock_paths):
    """Test loading when the responses file doesn't exist."""
    m_open = mock_open()
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", m_open) as mock_file_constructor,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        assert responses == {}
        assert response_data.RESPONSE_DATA_CACHE == {}  # Cache should be empty dict

        mock_log.warning.assert_called_once()
        assert mock_paths["responses"] in mock_log.warning.call_args[0][0]
        assert "not found or empty" in mock_log.warning.call_args[0][0]

        # Check that the default empty file was created
        mock_file_constructor.assert_called_with(mock_paths["responses"], "w", encoding="utf-8")
        handle = mock_file_constructor()
        handle.write.assert_called_once_with("{}")  # Default is empty dict for responses
        mock_log.info.assert_called_once_with(f"Created empty responses file at {mock_paths['responses']}")


def test_load_responses_empty_file(mock_paths):
    """Test loading when the responses file exists but is empty."""
    m_open = mock_open()
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=0),
        patch("builtins.open", m_open) as mock_file_constructor,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        assert responses == {}
        assert response_data.RESPONSE_DATA_CACHE == {}
        mock_log.warning.assert_called_once()
        assert "not found or empty" in mock_log.warning.call_args[0][0]
        # Check that the default empty file was created (overwritten)
        mock_file_constructor.assert_called_with(mock_paths["responses"], "w", encoding="utf-8")
        handle = mock_file_constructor()
        handle.write.assert_called_once_with("{}")
        mock_log.info.assert_called_once_with(f"Created empty responses file at {mock_paths['responses']}")


def test_load_responses_json_decode_error(mock_paths):
    """Test loading with invalid JSON content."""
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data="invalid json")),
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        assert responses == {}
        assert response_data.RESPONSE_DATA_CACHE == {}
        mock_log.error.assert_called_once()
        assert "Error decoding JSON" in mock_log.error.call_args[0][0]


def test_load_responses_not_a_dict(mock_paths):
    """Test loading when JSON is valid but not a dict."""
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data='["list", "instead"]')),
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        assert responses == {}
        assert response_data.RESPONSE_DATA_CACHE == {}
        mock_log.error.assert_called_once()
        assert "Expected a JSON object (dict)" in mock_log.error.call_args[0][0]


def test_load_responses_event_value_not_list(mock_paths):
    """Test loading when an event's value in old format is not a list (triggers migration warning)."""
    # Old format with bad data
    bad_json = json.dumps({"Event A": "not a list", "Event B": [RESP_3_DICT]})
    # Need to mock save_responses since migration will try to save
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=bad_json)),
        patch("offkai_bot.data.response.save_responses"),  # Mock save to avoid actual file write
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        # Event A should be skipped due to bad format in old-style data
        assert "Event A" not in responses or len(responses["Event A"]["attendees"]) == 0
        # Event B should be migrated successfully
        assert "Event B" in responses
        assert len(responses["Event B"]["attendees"]) == 1
        assert responses["Event B"]["attendees"][0] == RESP_3_OBJ
        mock_log.warning.assert_called()  # Should warn about bad data


def test_load_responses_item_not_dict(mock_paths):
    """Test loading when an item in a response list (old format) is not a dict."""
    bad_json = json.dumps({"Event A": ["not a dict", RESP_2_DICT], "Event B": [RESP_3_DICT]})
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=bad_json)),
        patch("offkai_bot.data.response.save_responses"),  # Mock save since migration will save
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        assert "Event A" in responses
        assert len(responses["Event A"]["attendees"]) == 1  # Only the valid dict should be loaded
        assert responses["Event A"]["attendees"][0] == RESP_2_OBJ
        assert "Event B" in responses  # Event B should load normally
        assert len(responses["Event B"]["attendees"]) == 1
        assert responses["Event B"]["attendees"][0] == RESP_3_OBJ

        mock_log.warning.assert_called()
        assert "Expected a dict" in str(mock_log.warning.call_args)


@patch("offkai_bot.data.response.datetime")  # Mock the datetime class itself
def test_load_responses_invalid_timestamp(mock_datetime, mock_paths):
    """Test loading data with an invalid timestamp string."""
    # Configure the mock datetime.now() before the test runs
    mock_now_time = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
    mock_datetime.now.return_value = mock_now_time

    def fromisoformat_side_effect(ts):
        if ts == "invalid-ts":
            raise ValueError("bad format")  # RAISE the exception
        else:
            # For valid strings, call the real fromisoformat (or simulate)
            # Be careful here - calling the real one might bypass other mocks
            # A safer approach might be to return a known valid datetime object
            # For simplicity, let's assume we only test the invalid case path here
            # and other tests cover valid paths. If you need valid paths in this
            # specific test, return a fixed valid datetime object.
            # return datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC) # Example fixed valid dt
            # OR if you are sure the real one is okay to call:
            return datetime.fromisoformat(ts)  # Call real one for valid strings

    mock_datetime.fromisoformat.side_effect = fromisoformat_side_effect

    invalid_ts_resp = RESP_1_DICT.copy()
    invalid_ts_resp["timestamp"] = "invalid-ts"
    invalid_json = json.dumps({"Event A": [invalid_ts_resp]})

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=invalid_json)),
        patch("offkai_bot.data.response.save_responses"),  # Mock save since migration will save
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        assert len(responses["Event A"]["attendees"]) == 1
        # Timestamp should default to the mocked datetime.now()
        assert responses["Event A"]["attendees"][0].timestamp == mock_now_time
        assert responses["Event A"]["attendees"][0].user_id == RESP_1_DICT["user_id"]  # Other fields loaded

        mock_log.warning.assert_called()
        assert "Could not parse ISO timestamp" in str(mock_log.warning.call_args)


def test_load_responses_invalid_numeric_field(mock_paths):
    """Test loading data with non-numeric extra_people."""
    bad_resp_dict = RESP_1_DICT.copy()
    bad_resp_dict["extra_people"] = "two"  # Invalid integer
    bad_json = json.dumps({"Event A": [bad_resp_dict, RESP_2_DICT]})

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=bad_json)),
        patch("offkai_bot.data.response.save_responses"),  # Mock save since migration will save
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        assert len(responses["Event A"]["attendees"]) == 1  # Only the valid response loaded
        assert responses["Event A"]["attendees"][0] == RESP_2_OBJ
        mock_log.error.assert_called_once()
        assert "Error creating Response object" in mock_log.error.call_args[0][0]
        assert "invalid literal for int()" in str(mock_log.error.call_args)  # Check specific error


# == load_responses Tests ==


def test_load_responses_uses_cache(mock_paths):
    """Test that load_responses returns cache if populated."""
    response_data.RESPONSE_DATA_CACHE = {"Event A": make_event_data([RESP_1_OBJ])}
    with patch("offkai_bot.data.response._load_responses") as mock_internal_load:
        responses = response_data.load_responses()
        assert responses == {"Event A": make_event_data([RESP_1_OBJ])}
        mock_internal_load.assert_not_called()


def test_load_responses_loads_if_cache_none(mock_paths):
    """Test that load_responses calls _load_responses if cache is None."""
    response_data.RESPONSE_DATA_CACHE = None
    with patch(
        "offkai_bot.data.response._load_responses", return_value={"Event B": [RESP_3_OBJ]}
    ) as mock_internal_load:
        responses = response_data.load_responses()
        assert responses == {"Event B": [RESP_3_OBJ]}
        mock_internal_load.assert_called_once()


# == save_responses Tests ==


def test_save_responses_success(mock_paths):
    """Test saving valid response data."""
    response_data.RESPONSE_DATA_CACHE = {
        "Event A": make_event_data([RESP_1_OBJ, RESP_2_OBJ]),
        "Event B": make_event_data([RESP_3_OBJ]),
    }

    m_open = mock_open()
    # Patch both open and json.dump
    with (
        patch("builtins.open", m_open) as mock_file_constructor,
        patch("json.dump") as mock_json_dump,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        response_data.save_responses()

        # 1. Check file was opened correctly
        mock_file_constructor.assert_called_once_with(mock_paths["responses"], "w", encoding="utf-8")

        # 2. Get the mock file handle that *should* have been passed to json.dump
        mock_file_handle = m_open()

        # 3. Check json.dump was called correctly
        mock_json_dump.assert_called_once()
        args, kwargs = mock_json_dump.call_args

        # Check the positional arguments passed to json.dump
        # args[0] should be the data to dump
        assert args[0] == response_data.RESPONSE_DATA_CACHE
        # args[1] should be the file handle
        assert args[1] is mock_file_handle  # Check it's the handle returned by mock_open

        # Check the keyword arguments passed to json.dump
        assert kwargs.get("indent") == 4
        assert kwargs.get("cls") == DataclassJSONEncoder
        assert kwargs.get("ensure_ascii") is False  # Use 'is False' for explicit boolean check

        # Check logs
        mock_log.error.assert_not_called()


def test_save_responses_cache_is_none(mock_paths):
    """Test saving when cache hasn't been loaded."""
    response_data.RESPONSE_DATA_CACHE = None
    with patch("builtins.open") as mock_file_constructor, patch("offkai_bot.data.response._log") as mock_log:
        response_data.save_responses()
        mock_file_constructor.assert_not_called()
        mock_log.error.assert_called_once()
        assert "Attempted to save response data before loading" in mock_log.error.call_args[0][0]


def test_save_responses_os_error(mock_paths):
    """Test handling OS error during file writing."""
    response_data.RESPONSE_DATA_CACHE = {"Event A": make_event_data([RESP_1_OBJ])}
    m_open = mock_open()
    m_open.side_effect = OSError("Permission denied")
    with patch("builtins.open", m_open), patch("offkai_bot.data.response._log") as mock_log:
        response_data.save_responses()
        mock_log.error.assert_called_once()
        assert "Error writing response data" in mock_log.error.call_args[0][0]
        assert "Permission denied" in str(mock_log.error.call_args)


# == get_responses Tests ==


def test_get_responses_found(mock_paths):
    """Test getting responses for an existing event."""
    response_data.RESPONSE_DATA_CACHE = {
        "Event A": make_event_data([RESP_1_OBJ, RESP_2_OBJ]),
        "Event B": make_event_data([RESP_3_OBJ]),
    }
    with patch("offkai_bot.data.response.load_responses", return_value=response_data.RESPONSE_DATA_CACHE) as mock_load:
        responses = response_data.get_responses("Event A")
        assert responses == [RESP_1_OBJ, RESP_2_OBJ]
        mock_load.assert_called_once()


def test_get_responses_not_found(mock_paths):
    """Test getting responses for a non-existent event."""
    response_data.RESPONSE_DATA_CACHE = {"Event A": make_event_data([RESP_1_OBJ])}
    with patch("offkai_bot.data.response.load_responses", return_value=response_data.RESPONSE_DATA_CACHE):
        responses = response_data.get_responses("NonExistent Event")
        assert responses == []  # Should return empty list


# == add_response Tests ==


def test_add_response_new(mock_paths):
    """Test adding a new response to an event."""
    # Simulate starting with Event A having one response
    initial_cache = {"Event A": make_event_data([RESP_1_OBJ])}
    response_data.RESPONSE_DATA_CACHE = initial_cache  # Set cache directly for test setup

    # Mock load_responses to return our controlled cache
    # Mock save_responses to check it gets called
    with (
        patch("offkai_bot.data.response.load_responses", return_value=initial_cache) as mock_load,
        patch("offkai_bot.data.response.save_responses") as mock_save,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        response_data.add_response("Event A", RESP_2_OBJ)  # Add the second response

        mock_load.assert_called_once()
        # Check cache was updated
        assert len(initial_cache["Event A"]["attendees"]) == 2
        assert RESP_1_OBJ in initial_cache["Event A"]["attendees"]
        assert RESP_2_OBJ in initial_cache["Event A"]["attendees"]
        # Check save was called
        mock_save.assert_called_once()
        mock_log.info.assert_called_once()
        assert f"Added response from user {RESP_2_OBJ.user_id}" in mock_log.info.call_args[0][0]
        mock_log.warning.assert_not_called()


def test_add_response_new_event(mock_paths):
    """Test adding a response when the event doesn't exist in cache yet."""
    initial_cache = {"Event A": make_event_data([RESP_1_OBJ])}  # Start without Event B
    response_data.RESPONSE_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.response.load_responses", return_value=initial_cache) as mock_load,
        patch("offkai_bot.data.response.save_responses") as mock_save,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        response_data.add_response("Event B", RESP_3_OBJ)  # Add response for new event

        mock_load.assert_called_once()
        # Check cache was updated
        assert "Event B" in initial_cache
        assert len(initial_cache["Event B"]["attendees"]) == 1
        assert initial_cache["Event B"]["attendees"][0] == RESP_3_OBJ
        # Check save was called
        mock_save.assert_called_once()
        mock_log.info.assert_called_once()
        assert f"Added response from user {RESP_3_OBJ.user_id}" in mock_log.info.call_args[0][0]


def test_add_response_duplicate(mock_paths):
    """Test adding a response when the user has already responded."""
    initial_cache = {"Event A": make_event_data([RESP_1_OBJ])}  # User 123 already responded
    response_data.RESPONSE_DATA_CACHE = initial_cache

    # Create a slightly different response object for the same user
    duplicate_resp = Response(
        user_id=123,
        username="User1 Updated",
        extra_people=2,
        behavior_confirmed=False,
        arrival_confirmed=False,
        event_name="Event A",
        timestamp=datetime.now(UTC),
        drinks=["Tea"],
    )

    with (
        patch("offkai_bot.data.response.load_responses", return_value=initial_cache) as mock_load,
        patch("offkai_bot.data.response.save_responses") as mock_save,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        with pytest.raises(DuplicateResponseError):
            response_data.add_response("Event A", duplicate_resp)

        mock_load.assert_called_once()
        # Check cache was NOT updated
        assert len(initial_cache["Event A"]["attendees"]) == 1
        assert initial_cache["Event A"]["attendees"][0] == RESP_1_OBJ  # Still the original response
        # Check save was NOT called
        mock_save.assert_not_called()
        # Check log warning
        mock_log.warning.assert_called_once()
        assert f"User {RESP_1_OBJ.user_id} already responded" in mock_log.warning.call_args[0][0]
        mock_log.info.assert_not_called()


# == remove_response Tests ==


def test_remove_response_found(mock_paths):
    """Test removing an existing response."""
    initial_cache = {"Event A": make_event_data([RESP_1_OBJ, RESP_2_OBJ])}
    response_data.RESPONSE_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.response.load_responses", return_value=initial_cache) as mock_load,
        patch("offkai_bot.data.response.save_responses") as mock_save,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        response_data.remove_response("Event A", RESP_1_OBJ.user_id)  # Remove User 1

        mock_load.assert_called_once()
        # Check cache was updated
        assert len(initial_cache["Event A"]["attendees"]) == 1
        assert initial_cache["Event A"]["attendees"][0] == RESP_2_OBJ  # Only User 2 remains
        # Check save was called
        mock_save.assert_called_once()
        mock_log.info.assert_called_once()
        assert f"Removed response from user {RESP_1_OBJ.user_id}" in mock_log.info.call_args[0][0]
        mock_log.warning.assert_not_called()


def test_remove_response_not_found_user(mock_paths):
    """Test removing a response for a user who hasn't responded."""
    initial_cache = {"Event A": make_event_data([RESP_1_OBJ])}
    response_data.RESPONSE_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.response.load_responses", return_value=initial_cache) as mock_load,
        patch("offkai_bot.data.response.save_responses") as mock_save,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        with pytest.raises(ResponseNotFoundError):
            response_data.remove_response("Event A", 999)  # Non-existent user ID

        mock_load.assert_called_once()
        # Check cache was NOT updated
        assert len(initial_cache["Event A"]["attendees"]) == 1
        assert initial_cache["Event A"]["attendees"][0] == RESP_1_OBJ
        # Check save was NOT called
        mock_save.assert_not_called()
        mock_log.warning.assert_called_once()
        assert "No response found for user 999" in mock_log.warning.call_args[0][0]
        mock_log.info.assert_not_called()


def test_remove_response_not_found_event(mock_paths):
    """Test removing a response for an event that doesn't exist in cache."""
    initial_cache = {"Event A": make_event_data([RESP_1_OBJ])}
    response_data.RESPONSE_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.response.load_responses", return_value=initial_cache) as mock_load,
        patch("offkai_bot.data.response.save_responses") as mock_save,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        with pytest.raises(ResponseNotFoundError):
            response_data.remove_response("NonExistent Event", RESP_1_OBJ.user_id)

        mock_load.assert_called_once()
        # Check cache was NOT updated
        assert len(initial_cache["Event A"]["attendees"]) == 1
        # Check save was NOT called
        mock_save.assert_not_called()
        mock_log.warning.assert_called_once()
        assert (
            f"No response found for user {RESP_1_OBJ.user_id} in event NonExistent Event"
            in mock_log.warning.call_args[0][0]
        )
        mock_log.info.assert_not_called()


# --- Migration Tests ---


def test_migration_old_format_responses_only(mock_paths):
    """Test migration from old format with only responses (no waitlist file)."""

    old_format_data = {
        "Event A": [RESP_1_DICT, RESP_2_DICT],
        "Event B": [RESP_3_DICT],
    }

    # Write old format to file
    with open(mock_paths["responses"], "w") as f:
        json.dump(old_format_data, f)

    # Clear cache to force reload
    response_data.RESPONSE_DATA_CACHE = None

    # Load responses - should trigger migration
    result = response_data.load_responses()

    # Verify new format structure
    assert "Event A" in result
    assert "Event B" in result
    assert "attendees" in result["Event A"]
    assert "waitlist" in result["Event A"]
    assert "attendees" in result["Event B"]
    assert "waitlist" in result["Event B"]

    # Verify attendees were migrated correctly
    assert len(result["Event A"]["attendees"]) == 2
    assert len(result["Event B"]["attendees"]) == 1
    assert result["Event A"]["attendees"][0].user_id == 123
    assert result["Event A"]["attendees"][1].user_id == 456
    assert result["Event B"]["attendees"][0].user_id == 789

    # Verify waitlists are empty
    assert len(result["Event A"]["waitlist"]) == 0
    assert len(result["Event B"]["waitlist"]) == 0

    # Verify file was saved in new format
    with open(mock_paths["responses"], "r") as f:
        saved_data = json.load(f)

    assert "attendees" in saved_data["Event A"]
    assert "waitlist" in saved_data["Event A"]


def test_migration_with_old_waitlist_file(mock_paths, mock_config):
    """Test migration from old format with both responses and waitlist files."""

    old_responses = {
        "Event A": [RESP_1_DICT],
    }

    old_waitlist = {
        "Event A": [
            {
                "user_id": 999,
                "username": "WaitlistUser",
                "extra_people": 0,
                "behavior_confirmed": True,
                "arrival_confirmed": True,
                "event_name": "Event A",
                "timestamp": NOW.isoformat(),
                "drinks": [],
            }
        ],
    }

    # Create old waitlist file
    waitlist_file = mock_paths["responses"].replace("test_responses.json", "test_waitlist.json")
    mock_config["WAITLIST_FILE"] = waitlist_file

    # Write old format files
    with open(mock_paths["responses"], "w") as f:
        json.dump(old_responses, f)
    with open(waitlist_file, "w") as f:
        json.dump(old_waitlist, f)

    # Clear cache
    response_data.RESPONSE_DATA_CACHE = None

    # Load responses - should trigger migration of both files
    with patch("offkai_bot.data.response.get_config", return_value=mock_config):
        result = response_data.load_responses()

    # Verify both attendees and waitlist were migrated
    assert len(result["Event A"]["attendees"]) == 1
    assert len(result["Event A"]["waitlist"]) == 1
    assert result["Event A"]["attendees"][0].user_id == 123
    assert result["Event A"]["waitlist"][0].user_id == 999

    # Verify file was saved in new format
    with open(mock_paths["responses"], "r") as f:
        saved_data = json.load(f)

    assert "attendees" in saved_data["Event A"]
    assert "waitlist" in saved_data["Event A"]
    assert len(saved_data["Event A"]["attendees"]) == 1
    assert len(saved_data["Event A"]["waitlist"]) == 1


def test_load_new_format_directly(mock_paths):
    """Test loading responses that are already in new format."""
    new_format_data = {
        "Event A": {
            "attendees": [RESP_1_DICT, RESP_2_DICT],
            "waitlist": [],
        },
        "Event B": {
            "attendees": [],
            "waitlist": [
                {
                    "user_id": 999,
                    "username": "WaitlistUser",
                    "extra_people": 1,
                    "behavior_confirmed": True,
                    "arrival_confirmed": True,
                    "event_name": "Event B",
                    "timestamp": NOW.isoformat(),
                    "drinks": [],
                }
            ],
        },
    }

    # Write new format to file
    with open(mock_paths["responses"], "w") as f:
        json.dump(new_format_data, f)

    # Clear cache
    response_data.RESPONSE_DATA_CACHE = None

    # Load responses - should NOT trigger migration
    result = response_data.load_responses()

    # Verify structure is preserved
    assert len(result["Event A"]["attendees"]) == 2
    assert len(result["Event A"]["waitlist"]) == 0
    assert len(result["Event B"]["attendees"]) == 0
    assert len(result["Event B"]["waitlist"]) == 1

    # Verify data is correct
    assert result["Event A"]["attendees"][0].user_id == 123
    assert result["Event B"]["waitlist"][0].user_id == 999


def test_get_waitlist_from_unified_structure(mock_paths):
    """Test get_waitlist function with new unified structure."""
    new_format_data = {
        "Event A": {
            "attendees": [RESP_1_DICT],
            "waitlist": [
                {
                    "user_id": 999,
                    "username": "WaitlistUser",
                    "extra_people": 0,
                    "behavior_confirmed": True,
                    "arrival_confirmed": True,
                    "event_name": "Event A",
                    "timestamp": NOW.isoformat(),
                    "drinks": [],
                }
            ],
        },
    }

    # Write new format to file
    with open(mock_paths["responses"], "w") as f:
        json.dump(new_format_data, f)

    # Clear cache
    response_data.RESPONSE_DATA_CACHE = None

    # Get waitlist
    waitlist = response_data.get_waitlist("Event A")

    assert len(waitlist) == 1
    assert waitlist[0].user_id == 999

    # Get responses (attendees)
    responses = response_data.get_responses("Event A")

    assert len(responses) == 1
    assert responses[0].user_id == 123


# --- Tests for extras_names field ---


def test_response_with_extras_names(mock_paths):
    """Test Response object with extras_names field."""
    assert RESP_4_OBJ.extras_names == ["Alice", "Bob"]
    assert RESP_4_OBJ.extra_people == 2
    assert RESP_4_OBJ.username == "User4"


def test_response_without_extras_names_defaults_to_empty(mock_paths):
    """Test Response object defaults to empty list when extras_names not provided."""
    assert RESP_1_OBJ.extras_names == []
    assert RESP_2_OBJ.extras_names == []
    assert RESP_3_OBJ.extras_names == []


def test_parse_response_with_extras_names(mock_paths):
    """Test parsing Response from dict with extras_names field."""
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=json.dumps({"Event A": [RESP_4_DICT]}))),
        patch("offkai_bot.data.response.save_responses"),
    ):
        responses = response_data._load_responses()

        assert len(responses["Event A"]["attendees"]) == 1
        loaded_resp = responses["Event A"]["attendees"][0]
        assert loaded_resp.extras_names == ["Alice", "Bob"]
        assert loaded_resp.user_id == 999
        assert loaded_resp.extra_people == 2


def test_parse_response_without_extras_names_field(mock_paths):
    """Test parsing Response from dict without extras_names field defaults to empty list."""
    # Use RESP_1_DICT which doesn't have extras_names
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=json.dumps({"Event A": [RESP_1_DICT]}))),
        patch("offkai_bot.data.response.save_responses"),
    ):
        responses = response_data._load_responses()

        assert len(responses["Event A"]["attendees"]) == 1
        loaded_resp = responses["Event A"]["attendees"][0]
        assert loaded_resp.extras_names == []  # Should default to empty list
        assert loaded_resp.user_id == 123


def test_save_response_with_extras_names(mock_paths):
    """Test saving Response with extras_names to file."""
    response_data.RESPONSE_DATA_CACHE = {"Event A": make_event_data([RESP_4_OBJ])}

    m_open = mock_open()
    with (
        patch("builtins.open", m_open),
        patch("json.dump") as mock_json_dump,
    ):
        response_data.save_responses()

        # Verify json.dump was called
        mock_json_dump.assert_called_once()
        args, kwargs = mock_json_dump.call_args

        # Check the data being saved includes extras_names
        saved_data = args[0]
        assert saved_data["Event A"]["attendees"][0].extras_names == ["Alice", "Bob"]


def test_waitlist_entry_with_extras_names(mock_paths):
    """Test WaitlistEntry object with extras_names field."""
    from offkai_bot.data.response import WaitlistEntry

    waitlist_entry = WaitlistEntry(
        user_id=888,
        username="WaitlistUser",
        extra_people=1,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="Event X",
        timestamp=NOW,
        drinks=["Tea"],
        extras_names=["Charlie"],
    )

    assert waitlist_entry.extras_names == ["Charlie"]
    assert waitlist_entry.extra_people == 1


def test_parse_waitlist_entry_with_extras_names(mock_paths):
    """Test parsing WaitlistEntry from dict with extras_names field."""
    waitlist_dict = {
        "user_id": 888,
        "username": "WaitlistUser",
        "extra_people": 1,
        "behavior_confirmed": True,
        "arrival_confirmed": True,
        "event_name": "Event A",
        "timestamp": NOW.isoformat(),
        "drinks": ["Tea"],
        "extras_names": ["Charlie"],
    }

    new_format_data = {
        "Event A": {
            "attendees": [],
            "waitlist": [waitlist_dict],
        },
    }

    with open(mock_paths["responses"], "w") as f:
        json.dump(new_format_data, f)

    response_data.RESPONSE_DATA_CACHE = None
    result = response_data.load_responses()

    assert len(result["Event A"]["waitlist"]) == 1
    loaded_entry = result["Event A"]["waitlist"][0]
    assert loaded_entry.extras_names == ["Charlie"]
    assert loaded_entry.user_id == 888


def test_parse_waitlist_entry_without_extras_names_field(mock_paths):
    """Test parsing WaitlistEntry from dict without extras_names field defaults to empty list."""
    waitlist_dict = {
        "user_id": 888,
        "username": "WaitlistUser",
        "extra_people": 1,
        "behavior_confirmed": True,
        "arrival_confirmed": True,
        "event_name": "Event A",
        "timestamp": NOW.isoformat(),
        "drinks": [],
        # No extras_names field
    }

    new_format_data = {
        "Event A": {
            "attendees": [],
            "waitlist": [waitlist_dict],
        },
    }

    with open(mock_paths["responses"], "w") as f:
        json.dump(new_format_data, f)

    response_data.RESPONSE_DATA_CACHE = None
    result = response_data.load_responses()

    assert len(result["Event A"]["waitlist"]) == 1
    loaded_entry = result["Event A"]["waitlist"][0]
    assert loaded_entry.extras_names == []  # Should default to empty list


# --- Tests for calculate_attendance with extras_names ---


def test_calculate_attendance_with_extras_names(mock_paths):
    """Test calculate_attendance shows extras names properly formatted."""
    # Create responses with extras names
    resp_with_extras = Response(
        user_id=111,
        username="UserA",
        extra_people=2,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="Event X",
        timestamp=datetime.now(UTC),
        drinks=[],
        extras_names=["Alice", "Bob"],
    )

    response_data.RESPONSE_DATA_CACHE = {"Event X": make_event_data([resp_with_extras])}

    with patch("offkai_bot.data.response.load_responses", return_value=response_data.RESPONSE_DATA_CACHE):
        total_count, attendee_names = response_data.calculate_attendance("Event X")

    # Should have 3 total attendees (1 primary + 2 extras)
    assert total_count == 3
    assert len(attendee_names) == 3

    # Check the names are formatted correctly
    assert attendee_names[0] == "UserA"
    assert attendee_names[1] == "Alice (UserA +1)"
    assert attendee_names[2] == "Bob (UserA +2)"


def test_calculate_attendance_multiple_users_with_extras_names(mock_paths):
    """Test calculate_attendance with multiple users having extras with names."""
    resp1 = Response(
        user_id=111,
        username="UserA",
        extra_people=2,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="Event Y",
        timestamp=datetime.now(UTC),
        drinks=[],
        extras_names=["Alice", "Bob"],
    )

    resp2 = Response(
        user_id=222,
        username="UserB",
        extra_people=1,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="Event Y",
        timestamp=datetime.now(UTC),
        drinks=[],
        extras_names=["Charlie"],
    )

    resp3 = Response(
        user_id=333,
        username="UserC",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="Event Y",
        timestamp=datetime.now(UTC),
        drinks=[],
        extras_names=[],
    )

    response_data.RESPONSE_DATA_CACHE = {"Event Y": make_event_data([resp1, resp2, resp3])}

    with patch("offkai_bot.data.response.load_responses", return_value=response_data.RESPONSE_DATA_CACHE):
        total_count, attendee_names = response_data.calculate_attendance("Event Y")

    # Should have 6 total attendees (3 primary + 2 extras from resp1 + 1 extra from resp2)
    assert total_count == 6
    assert len(attendee_names) == 6

    # Check the names are in the list
    assert "UserA" in attendee_names
    assert "Alice (UserA +1)" in attendee_names
    assert "Bob (UserA +2)" in attendee_names
    assert "UserB" in attendee_names
    assert "Charlie (UserB +1)" in attendee_names
    assert "UserC" in attendee_names


def test_calculate_attendance_no_extras(mock_paths):
    """Test calculate_attendance with users having no extras."""
    resp1 = Response(
        user_id=111,
        username="UserA",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="Event Z",
        timestamp=datetime.now(UTC),
        drinks=[],
        extras_names=[],
    )

    resp2 = Response(
        user_id=222,
        username="UserB",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="Event Z",
        timestamp=datetime.now(UTC),
        drinks=[],
        extras_names=[],
    )

    response_data.RESPONSE_DATA_CACHE = {"Event Z": make_event_data([resp1, resp2])}

    with patch("offkai_bot.data.response.load_responses", return_value=response_data.RESPONSE_DATA_CACHE):
        total_count, attendee_names = response_data.calculate_attendance("Event Z")

    # Should have 2 total attendees
    assert total_count == 2
    assert len(attendee_names) == 2
    assert "UserA" in attendee_names
    assert "UserB" in attendee_names
