# tests/data/test_response.py
import json
from datetime import UTC, datetime
from unittest.mock import mock_open, patch

# Import the module we are testing
from offkai_bot.data import response as response_data
from offkai_bot.data.encoders import DataclassJSONEncoder  # Needed for save verification
from offkai_bot.data.response import Response  # Import the dataclass too

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

RESP_1_OBJ = Response(**{k: (NOW if k == "timestamp" else v) for k, v in RESP_1_DICT.items()})
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
RESP_3_OBJ = Response(**{k: (NOW if k == "timestamp" else v) for k, v in RESP_3_DICT.items()})


VALID_RESPONSES_DICT = {"Event A": [RESP_1_DICT, RESP_2_DICT], "Event B": [RESP_3_DICT]}
VALID_RESPONSES_JSON = json.dumps(VALID_RESPONSES_DICT, indent=4)
EMPTY_RESPONSES_JSON = json.dumps({}, indent=4)

# --- Tests ---


# == _load_responses Tests ==


def test_load_responses_success(mock_paths):
    """Test loading valid response data from a file."""
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
        assert len(responses["Event A"]) == 2
        assert len(responses["Event B"]) == 1

        # Compare loaded objects carefully due to bool conversion
        assert responses["Event A"][0] == RESP_1_OBJ
        assert responses["Event A"][1] == RESP_2_OBJ
        assert responses["Event B"][0] == RESP_3_OBJ

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
    """Test loading when an event's value is not a list of responses."""
    bad_json = json.dumps({"Event A": "not a list", "Event B": [RESP_3_DICT]})
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=bad_json)),
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        assert "Event A" not in responses  # Event A should be skipped
        assert "Event B" in responses
        assert len(responses["Event B"]) == 1
        assert responses["Event B"][0] == RESP_3_OBJ
        mock_log.warning.assert_called_once()
        assert "Expected a list, got <class 'str'>" in mock_log.warning.call_args[0][0]


def test_load_responses_item_not_dict(mock_paths):
    """Test loading when an item in a response list is not a dict."""
    bad_json = json.dumps({"Event A": ["not a dict", RESP_2_DICT], "Event B": [RESP_3_DICT]})
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=bad_json)),
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        assert "Event A" in responses
        assert len(responses["Event A"]) == 1  # Only the valid dict should be loaded
        assert responses["Event A"][0] == RESP_2_OBJ
        assert "Event B" in responses  # Event B should load normally
        assert len(responses["Event B"]) == 1
        assert responses["Event B"][0] == RESP_3_OBJ

        mock_log.warning.assert_called_once()
        assert "Expected a dict, got <class 'str'>" in mock_log.warning.call_args[0][0]


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
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        assert len(responses["Event A"]) == 1
        # Timestamp should default to the mocked datetime.now()
        assert responses["Event A"][0].timestamp == mock_now_time
        assert responses["Event A"][0].user_id == RESP_1_DICT["user_id"]  # Other fields loaded

        mock_log.warning.assert_called_once()
        assert "Could not parse ISO timestamp" in mock_log.warning.call_args[0][0]
        assert "'invalid-ts'" in mock_log.warning.call_args[0][0]


def test_load_responses_invalid_numeric_field(mock_paths):
    """Test loading data with non-numeric extra_people."""
    bad_resp_dict = RESP_1_DICT.copy()
    bad_resp_dict["extra_people"] = "two"  # Invalid integer
    bad_json = json.dumps({"Event A": [bad_resp_dict, RESP_2_DICT]})

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=bad_json)),
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        responses = response_data._load_responses()

        assert len(responses["Event A"]) == 1  # Only the valid response loaded
        assert responses["Event A"][0] == RESP_2_OBJ
        mock_log.error.assert_called_once()
        assert "Error creating Response object" in mock_log.error.call_args[0][0]
        assert "invalid literal for int()" in str(mock_log.error.call_args)  # Check specific error


# == load_responses Tests ==


def test_load_responses_uses_cache(mock_paths):
    """Test that load_responses returns cache if populated."""
    response_data.RESPONSE_DATA_CACHE = {"Event A": [RESP_1_OBJ]}
    with patch("offkai_bot.data.response._load_responses") as mock_internal_load:
        responses = response_data.load_responses()
        assert responses == {"Event A": [RESP_1_OBJ]}
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
    response_data.RESPONSE_DATA_CACHE = {"Event A": [RESP_1_OBJ, RESP_2_OBJ], "Event B": [RESP_3_OBJ]}

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
    response_data.RESPONSE_DATA_CACHE = {"Event A": [RESP_1_OBJ]}
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
    response_data.RESPONSE_DATA_CACHE = {"Event A": [RESP_1_OBJ, RESP_2_OBJ], "Event B": [RESP_3_OBJ]}
    with patch("offkai_bot.data.response.load_responses", return_value=response_data.RESPONSE_DATA_CACHE) as mock_load:
        responses = response_data.get_responses("Event A")
        assert responses == [RESP_1_OBJ, RESP_2_OBJ]
        mock_load.assert_called_once()


def test_get_responses_not_found(mock_paths):
    """Test getting responses for a non-existent event."""
    response_data.RESPONSE_DATA_CACHE = {"Event A": [RESP_1_OBJ]}
    with patch("offkai_bot.data.response.load_responses", return_value=response_data.RESPONSE_DATA_CACHE):
        responses = response_data.get_responses("NonExistent Event")
        assert responses == []  # Should return empty list


# == add_response Tests ==


def test_add_response_new(mock_paths):
    """Test adding a new response to an event."""
    # Simulate starting with Event A having one response
    initial_cache = {"Event A": [RESP_1_OBJ]}
    response_data.RESPONSE_DATA_CACHE = initial_cache  # Set cache directly for test setup

    # Mock load_responses to return our controlled cache
    # Mock save_responses to check it gets called
    with (
        patch("offkai_bot.data.response.load_responses", return_value=initial_cache) as mock_load,
        patch("offkai_bot.data.response.save_responses") as mock_save,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        result = response_data.add_response("Event A", RESP_2_OBJ)  # Add the second response

        assert result is True
        mock_load.assert_called_once()
        # Check cache was updated
        assert len(initial_cache["Event A"]) == 2
        assert RESP_1_OBJ in initial_cache["Event A"]
        assert RESP_2_OBJ in initial_cache["Event A"]
        # Check save was called
        mock_save.assert_called_once()
        mock_log.info.assert_called_once()
        assert f"Added response from user {RESP_2_OBJ.user_id}" in mock_log.info.call_args[0][0]
        mock_log.warning.assert_not_called()


def test_add_response_new_event(mock_paths):
    """Test adding a response when the event doesn't exist in cache yet."""
    initial_cache = {"Event A": [RESP_1_OBJ]}  # Start without Event B
    response_data.RESPONSE_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.response.load_responses", return_value=initial_cache) as mock_load,
        patch("offkai_bot.data.response.save_responses") as mock_save,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        result = response_data.add_response("Event B", RESP_3_OBJ)  # Add response for new event

        assert result is True
        mock_load.assert_called_once()
        # Check cache was updated
        assert "Event B" in initial_cache
        assert len(initial_cache["Event B"]) == 1
        assert initial_cache["Event B"][0] == RESP_3_OBJ
        # Check save was called
        mock_save.assert_called_once()
        mock_log.info.assert_called_once()
        assert f"Added response from user {RESP_3_OBJ.user_id}" in mock_log.info.call_args[0][0]


def test_add_response_duplicate(mock_paths):
    """Test adding a response when the user has already responded."""
    initial_cache = {"Event A": [RESP_1_OBJ]}  # User 123 already responded
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
        result = response_data.add_response("Event A", duplicate_resp)

        assert result is False  # Should fail
        mock_load.assert_called_once()
        # Check cache was NOT updated
        assert len(initial_cache["Event A"]) == 1
        assert initial_cache["Event A"][0] == RESP_1_OBJ  # Still the original response
        # Check save was NOT called
        mock_save.assert_not_called()
        # Check log warning
        mock_log.warning.assert_called_once()
        assert f"User {RESP_1_OBJ.user_id} already responded" in mock_log.warning.call_args[0][0]
        mock_log.info.assert_not_called()


# == remove_response Tests ==


def test_remove_response_found(mock_paths):
    """Test removing an existing response."""
    initial_cache = {"Event A": [RESP_1_OBJ, RESP_2_OBJ]}
    response_data.RESPONSE_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.response.load_responses", return_value=initial_cache) as mock_load,
        patch("offkai_bot.data.response.save_responses") as mock_save,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        result = response_data.remove_response("Event A", RESP_1_OBJ.user_id)  # Remove User 1

        assert result is True
        mock_load.assert_called_once()
        # Check cache was updated
        assert len(initial_cache["Event A"]) == 1
        assert initial_cache["Event A"][0] == RESP_2_OBJ  # Only User 2 remains
        # Check save was called
        mock_save.assert_called_once()
        mock_log.info.assert_called_once()
        assert f"Removed response from user {RESP_1_OBJ.user_id}" in mock_log.info.call_args[0][0]
        mock_log.warning.assert_not_called()


def test_remove_response_not_found_user(mock_paths):
    """Test removing a response for a user who hasn't responded."""
    initial_cache = {"Event A": [RESP_1_OBJ]}
    response_data.RESPONSE_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.response.load_responses", return_value=initial_cache) as mock_load,
        patch("offkai_bot.data.response.save_responses") as mock_save,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        result = response_data.remove_response("Event A", 999)  # Non-existent user ID

        assert result is False
        mock_load.assert_called_once()
        # Check cache was NOT updated
        assert len(initial_cache["Event A"]) == 1
        assert initial_cache["Event A"][0] == RESP_1_OBJ
        # Check save was NOT called
        mock_save.assert_not_called()
        mock_log.warning.assert_called_once()
        assert "No response found for user 999" in mock_log.warning.call_args[0][0]
        mock_log.info.assert_not_called()


def test_remove_response_not_found_event(mock_paths):
    """Test removing a response for an event that doesn't exist in cache."""
    initial_cache = {"Event A": [RESP_1_OBJ]}
    response_data.RESPONSE_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.response.load_responses", return_value=initial_cache) as mock_load,
        patch("offkai_bot.data.response.save_responses") as mock_save,
        patch("offkai_bot.data.response._log") as mock_log,
    ):
        result = response_data.remove_response("NonExistent Event", RESP_1_OBJ.user_id)

        assert result is False
        mock_load.assert_called_once()
        # Check cache was NOT updated
        assert len(initial_cache["Event A"]) == 1
        # Check save was NOT called
        mock_save.assert_not_called()
        mock_log.warning.assert_called_once()
        assert (
            f"No response found for user {RESP_1_OBJ.user_id} in event NonExistent Event"
            in mock_log.warning.call_args[0][0]
        )
        mock_log.info.assert_not_called()
