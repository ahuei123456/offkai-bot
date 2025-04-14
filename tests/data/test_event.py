# tests/data/test_event.py
import json
from typing import Any
from datetime import UTC, datetime
from unittest.mock import mock_open, patch

import pytest

# Import the module we are testing
from offkai_bot.data import event as event_data
from offkai_bot.data.encoders import DataclassJSONEncoder  # Needed for save verification
from offkai_bot.data.event import OFFKAI_MESSAGE, Event, create_event_message
from offkai_bot.errors import EventNotFoundError  # Import the dataclass too

# --- Test Data ---
NOW = datetime.now(UTC)
EVENT_1_DICT: dict[str, Any] = {
    "event_name": "Test Event 1",
    "venue": "Venue 1",
    "address": "Addr 1",
    "google_maps_link": "gmap1",
    "event_datetime": NOW.isoformat(),
    "message": "Msg 1",
    "channel_id": 101,
    "message_id": 201,
    "open": True,
    "archived": False,
    "drinks": ["Beer", "Wine"],
}
EVENT_2_DICT: dict[str, Any] = {
    "event_name": "Test Event 2",
    "venue": "Venue 2",
    "address": "Addr 2",
    "google_maps_link": "gmap2",
    "event_datetime": None,  # No datetime
    "message": None,
    "channel_id": 102,
    "message_id": 202,
    "open": False,
    "archived": True,
    "drinks": [],
}
EVENT_1_OBJ = Event(
    event_name="Test Event 1",
    venue="Venue 1",
    address="Addr 1",
    google_maps_link="gmap1",
    event_datetime=NOW,
    message="Msg 1",
    channel_id=101,
    message_id=201,
    open=True,
    archived=False,
    drinks=["Beer", "Wine"],
)

EVENT_2_OBJ = Event(
    event_name="Test Event 2",
    venue="Venue 2",
    address="Addr 2",
    google_maps_link="gmap2",
    event_datetime=None,
    message=None,
    channel_id=102,
    message_id=202,
    open=False,
    archived=True,
    drinks=[],
)  # Handle None datetime explicitly

VALID_EVENTS_JSON = json.dumps([EVENT_1_DICT, EVENT_2_DICT], indent=4)
EMPTY_EVENTS_JSON = json.dumps([], indent=4)

# --- Tests ---


# == _load_event_data Tests ==


def test_load_event_data_success(mock_paths):
    """Test loading valid event data from a file."""
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=VALID_EVENTS_JSON)) as mock_file,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()

        mock_file.assert_called_once_with(mock_paths["events"], "r", encoding="utf-8")
        assert len(events) == 2
        assert events[0] == EVENT_1_OBJ  # Compare dataclass instances
        assert events[1] == EVENT_2_OBJ
        assert events == event_data.EVENT_DATA_CACHE  # Check cache is set
        mock_log.warning.assert_not_called()
        mock_log.error.assert_not_called()


def test_load_event_data_file_not_found(mock_paths):
    """Test loading when the events file doesn't exist."""
    # Mock os.path.exists to return False
    # Mock open: first check (read) raises implicitly, second check (write) succeeds
    m_open = mock_open()
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", m_open) as mock_file_constructor,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()

        assert events == []
        assert event_data.EVENT_DATA_CACHE == []  # Cache should be empty list

        # Check log message
        mock_log.warning.assert_called_once()
        assert mock_paths["events"] in mock_log.warning.call_args[0][0]
        assert "not found or empty" in mock_log.warning.call_args[0][0]

        # Check that the default empty file was created
        mock_file_constructor.assert_called_with(mock_paths["events"], "w", encoding="utf-8")
        handle = mock_file_constructor()
        handle.write.assert_called_once_with("[]")  # Default is empty list for events
        mock_log.info.assert_called_once_with(f"Created empty events file at {mock_paths['events']}")


def test_load_event_data_empty_file(mock_paths):
    """Test loading when the events file exists but is empty."""
    m_open = mock_open()
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=0),
        patch("builtins.open", m_open) as mock_file_constructor,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()

        assert events == []
        assert event_data.EVENT_DATA_CACHE == []
        mock_log.warning.assert_called_once()
        assert "not found or empty" in mock_log.warning.call_args[0][0]
        # Check that the default empty file was created (overwritten)
        mock_file_constructor.assert_called_with(mock_paths["events"], "w", encoding="utf-8")
        handle = mock_file_constructor()
        handle.write.assert_called_once_with("[]")
        mock_log.info.assert_called_once_with(f"Created empty events file at {mock_paths['events']}")


def test_load_event_data_json_decode_error(mock_paths):
    """Test loading with invalid JSON content."""
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data="invalid json")),
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()

        assert events == []
        assert event_data.EVENT_DATA_CACHE == []
        mock_log.error.assert_called_once()
        assert "Error decoding JSON" in mock_log.error.call_args[0][0]


def test_load_event_data_not_a_list(mock_paths):
    """Test loading when JSON is valid but not a list."""
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data='{"key": "value"}')),
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()

        assert events == []
        assert event_data.EVENT_DATA_CACHE == []
        mock_log.error.assert_called_once()
        assert "Expected a JSON list" in mock_log.error.call_args[0][0]


def test_load_event_data_invalid_datetime(mock_paths):
    """Test loading data with an invalid datetime string."""
    invalid_dt_event = EVENT_1_DICT.copy()
    invalid_dt_event["event_datetime"] = "not-a-datetime"
    invalid_json = json.dumps([invalid_dt_event])

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=invalid_json)),
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()

        assert len(events) == 1
        assert events[0].event_datetime is None  # Datetime should be None
        assert events[0].event_name == EVENT_1_DICT["event_name"]  # Other fields should be loaded
        mock_log.warning.assert_called_once()
        assert "Could not parse ISO datetime" in mock_log.warning.call_args[0][0]
        assert "'not-a-datetime'" in mock_log.warning.call_args[0][0]


def test_load_event_data_missing_required_field(mock_paths):
    """Test loading data where a dict is missing a required Event field."""
    bad_event_dict = EVENT_1_DICT.copy()
    del bad_event_dict["event_name"]  # Remove a required field
    bad_json = json.dumps([bad_event_dict, EVENT_2_DICT])  # Include a good one too

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=bad_json)),
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()

        assert len(events) == 1  # Only the valid event should be loaded
        assert events[0] == EVENT_2_OBJ
        mock_log.error.assert_called_once()
        assert "Skipping event entry due to missing or empty 'event_name'." in mock_log.error.call_args[0][0]
        # Check that the problematic dict is logged (or part of it)
        assert "'venue': 'Venue 1'" in str(mock_log.error.call_args)


# == load_event_data Tests ==


def test_load_event_data_uses_cache(mock_paths):
    """Test that load_event_data returns cache if populated."""
    # Pre-populate cache
    event_data.EVENT_DATA_CACHE = [EVENT_1_OBJ]

    # Patch _load_event_data to ensure it's NOT called
    with patch("offkai_bot.data.event._load_event_data") as mock_internal_load:
        events = event_data.load_event_data()
        assert events == [EVENT_1_OBJ]
        mock_internal_load.assert_not_called()


def test_load_event_data_loads_if_cache_none(mock_paths):
    """Test that load_event_data calls _load_event_data if cache is None."""
    event_data.EVENT_DATA_CACHE = None  # Ensure cache is empty

    # Patch _load_event_data to track calls and return something
    with patch("offkai_bot.data.event._load_event_data", return_value=[EVENT_2_OBJ]) as mock_internal_load:
        events = event_data.load_event_data()
        assert events == [EVENT_2_OBJ]
        mock_internal_load.assert_called_once()


# == save_event_data Tests ==


def test_save_event_data_success(mock_paths):
    """Test saving valid event data."""
    event_data.EVENT_DATA_CACHE = [EVENT_1_OBJ, EVENT_2_OBJ]  # Populate cache

    m_open = mock_open()
    # Patch both open and json.dump
    with (
        patch("builtins.open", m_open) as mock_file_constructor,
        patch("json.dump") as mock_json_dump,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        event_data.save_event_data()

        # 1. Check file was opened correctly
        mock_file_constructor.assert_called_once_with(mock_paths["events"], "w", encoding="utf-8")

        # 2. Get the mock file handle that *should* have been passed to json.dump
        #    mock_open returns the same mock handle every time it's called within the context
        mock_file_handle = m_open()

        # 3. Check json.dump was called correctly
        mock_json_dump.assert_called_once()
        args, kwargs = mock_json_dump.call_args

        # Check the positional arguments passed to json.dump
        # args[0] should be the data to dump
        assert args[0] == event_data.EVENT_DATA_CACHE
        # args[1] should be the file handle
        assert args[1] is mock_file_handle  # Check it's the handle returned by mock_open

        # Check the keyword arguments passed to json.dump
        assert kwargs.get("indent") == 4
        assert kwargs.get("cls") == DataclassJSONEncoder
        assert kwargs.get("ensure_ascii") is False  # Use 'is False' for explicit boolean check

        # Check logs
        mock_log.error.assert_not_called()


def test_save_event_data_cache_is_none(mock_paths):
    """Test saving when cache hasn't been loaded."""
    event_data.EVENT_DATA_CACHE = None

    with patch("builtins.open") as mock_file_constructor, patch("offkai_bot.data.event._log") as mock_log:
        event_data.save_event_data()

        mock_file_constructor.assert_not_called()  # Should not attempt to open file
        mock_log.error.assert_called_once()
        assert "Attempted to save event data before loading" in mock_log.error.call_args[0][0]


def test_save_event_data_os_error(mock_paths):
    """Test handling OS error during file writing."""
    event_data.EVENT_DATA_CACHE = [EVENT_1_OBJ]  # Populate cache
    m_open = mock_open()
    m_open.side_effect = OSError("Disk full")  # Simulate error on open('w')

    with patch("builtins.open", m_open), patch("offkai_bot.data.event._log") as mock_log:
        event_data.save_event_data()

        mock_log.error.assert_called_once()
        assert "Error writing event data" in mock_log.error.call_args[0][0]
        assert "Disk full" in str(mock_log.error.call_args)


# == get_event Tests ==


def test_get_event_found(mock_paths):
    """Test getting an existing event by name (case-insensitive)."""
    event_data.EVENT_DATA_CACHE = [EVENT_1_OBJ, EVENT_2_OBJ]  # Pre-populate cache

    # Patch load_event_data to ensure it's not re-loading unnecessarily
    with patch("offkai_bot.data.event.load_event_data", return_value=event_data.EVENT_DATA_CACHE) as mock_load:
        found_event = event_data.get_event("test event 1")  # Use different case
        assert found_event == EVENT_1_OBJ
        mock_load.assert_called_once()  # Should still call load once to get data

        found_event_exact = event_data.get_event("Test Event 2")
        assert found_event_exact == EVENT_2_OBJ


def test_get_event_not_found(mock_paths):
    """Test getting a non-existent event raises EventNotFoundError."""
    event_data.EVENT_DATA_CACHE = [EVENT_1_OBJ]  # Pre-populate cache
    non_existent_name = "NonExistent Event"

    # Patch load_event_data to ensure it uses the pre-populated cache
    with patch("offkai_bot.data.event.load_event_data", return_value=event_data.EVENT_DATA_CACHE):
        # Use pytest.raises to assert that the specific error is raised
        with pytest.raises(EventNotFoundError) as exc_info:
            event_data.get_event(non_existent_name)

        # Optionally, assert details about the exception instance
        assert exc_info.value.event_name == non_existent_name
        assert f"Event '{non_existent_name}' not found." in str(exc_info.value)


# == add_event Tests ==


def test_add_event(mock_paths):
    """Test adding a new event to the cache."""
    # 1. Setup the initial state of the cache directly.
    #    This simulates the state *after* a load would have happened.
    initial_cache_state = []
    event_data.EVENT_DATA_CACHE = initial_cache_state

    # 2. Mock load_event_data to simply return the *current* cache state.
    #    Also mock save_event_data to ensure add_event doesn't call it.
    with (
        patch("offkai_bot.data.event.load_event_data", return_value=event_data.EVENT_DATA_CACHE) as mock_load,
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        # 3. Call the function under test
        new_event_obj = event_data.add_event(
            event_name="New Event",
            venue="New Venue",
            address="New Addr",
            google_maps_link="new_gmap",
            event_datetime=NOW,
            thread_id=12345,
            drinks_list=["Juice"],
            announce_msg="Announcement!",
        )

        # 4. Assertions
        # Check the returned object properties (as before)
        assert isinstance(new_event_obj, Event)
        assert new_event_obj.event_name == "New Event"
        assert new_event_obj.venue == "New Venue"
        assert new_event_obj.address == "New Addr"
        assert new_event_obj.google_maps_link == "new_gmap"
        assert new_event_obj.event_datetime == NOW
        assert new_event_obj.channel_id == 12345
        assert new_event_obj.message_id is None
        assert new_event_obj.open is True
        assert new_event_obj.archived is False
        assert new_event_obj.drinks == ["Juice"]
        assert new_event_obj.message == "Announcement!"

        # Check that load_event_data was called (to retrieve the cache)
        mock_load.assert_called_once()

        # Check that the list object referenced by the global cache was modified
        assert len(initial_cache_state) == 1
        assert initial_cache_state[0] == new_event_obj
        # Verify the global cache variable still points to the modified list
        assert event_data.EVENT_DATA_CACHE is initial_cache_state

        # Check that save_event_data was NOT called by add_event
        mock_save.assert_not_called()

        # Check log message
        mock_log.info.assert_called_once()
        assert "'New Event' added to cache" in mock_log.info.call_args[0][0]


# == Event Dataclass Method Tests (Optional but good) ==


def test_event_format_details():
    """Test the format_details method of the Event dataclass."""
    dt = datetime(2024, 3, 15, 18, 30, 0)
    event = Event(
        event_name="Formatting Test",
        venue="Test Venue",
        address="123 Test St",
        google_maps_link="gmap_link",
        event_datetime=dt,
        drinks=["Soda", "Water"],
    )
    expected = (
        "📅 **Event Name**: Formatting Test\n"
        "🍽️ **Venue**: Test Venue\n"
        "📍 **Address**: 123 Test St\n"
        "🌎 **Google Maps Link**: gmap_link\n"
        "🕑 **Date and Time**: 2024-03-15 18:30 JST\n"  # Assumes JST formatting
        "🍺 **Drinks**: Soda, Water"
    )
    assert event.format_details() == expected


def test_event_format_details_no_datetime_no_drinks():
    """Test format_details with missing optional fields."""
    event = Event(
        event_name="Minimal Test",
        venue="Min Venue",
        address="Min Addr",
        google_maps_link="min_gmap",
        event_datetime=None,
        drinks=[],
    )
    expected = (
        "📅 **Event Name**: Minimal Test\n"
        "🍽️ **Venue**: Min Venue\n"
        "📍 **Address**: Min Addr\n"
        "🌎 **Google Maps Link**: min_gmap\n"
        "🕑 **Date and Time**: Not Set\n"
        "🍺 **Drinks**: No selection needed!"
    )
    assert event.format_details() == expected


def test_event_has_drinks():
    """Test the has_drinks property."""
    event_with = Event("N", "V", "A", "G", drinks=["A"])
    event_without = Event("N", "V", "A", "G", drinks=[])
    assert event_with.has_drinks is True
    assert event_without.has_drinks is False


def test_create_event_message():
    """Test the creation of the full event announcement message."""
    # Arrange: Create a sample event
    dt = datetime(2024, 7, 20, 20, 0, 0)
    event = Event(
        event_name="Message Test Event",
        venue="Test Cafe",
        address="456 Test Ave",
        google_maps_link="gmap_link_msg",
        event_datetime=dt,
        drinks=["Coffee", "Tea"],
    )

    # Act: Call the function under test
    actual_message = create_event_message(event)

    # Assert: Construct the expected message and compare
    expected_details = (
        "📅 **Event Name**: Message Test Event\n"
        "🍽️ **Venue**: Test Cafe\n"
        "📍 **Address**: 456 Test Ave\n"
        "🌎 **Google Maps Link**: gmap_link_msg\n"
        "🕑 **Date and Time**: 2024-07-20 20:00 JST\n"
        "🍺 **Drinks**: Coffee, Tea"
    )
    expected_message = f"{expected_details}\n\n{OFFKAI_MESSAGE}\nClick the button below to confirm your attendance!"

    assert actual_message == expected_message
