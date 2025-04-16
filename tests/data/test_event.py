# tests/data/test_event.py
import copy
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import mock_open, patch

import pytest

# Import the module we are testing
from offkai_bot.data import event as event_data
from offkai_bot.data.encoders import DataclassJSONEncoder  # Needed for save verification
from offkai_bot.data.event import JST, OFFKAI_MESSAGE, Event, create_event_message
from offkai_bot.errors import (
    EventAlreadyArchivedError,
    EventAlreadyClosedError,
    EventAlreadyOpenError,
    EventArchivedError,
    EventNotFoundError,
    InvalidDateTimeFormatError,
    NoChangesProvidedError,
)  # Import the dataclass too

# --- Test Data ---
# Use aware UTC datetimes for consistency
NOW_UTC = datetime.now(UTC)
LATER_UTC = NOW_UTC + timedelta(days=10)

# Base Event for modification tests - useful for specific state setups
BASE_EVENT_OBJ = Event(
    event_name="Base Event",
    venue="Base Venue",
    address="Base Addr",
    google_maps_link="base_gmap",
    event_datetime=NOW_UTC,
    event_deadline=LATER_UTC,
    message="Base Msg",
    channel_id=500,
    thread_id=501,
    message_id=502,
    open=True,
    archived=False,
    drinks=["Water", "Juice"],
)

# Specific state objects derived from BASE_EVENT_OBJ for testing status changes
EVENT_OPEN_NOT_ARCHIVED = copy.deepcopy(BASE_EVENT_OBJ)  # Ensure clean copy
EVENT_CLOSED_NOT_ARCHIVED = copy.deepcopy(BASE_EVENT_OBJ)
EVENT_CLOSED_NOT_ARCHIVED.open = False
EVENT_CLOSED_NOT_ARCHIVED.event_name = "Closed Event"  # Give distinct name if needed
EVENT_ARCHIVED = copy.deepcopy(BASE_EVENT_OBJ)
EVENT_ARCHIVED.open = False
EVENT_ARCHIVED.archived = True
EVENT_ARCHIVED.event_name = "Archived Event"  # Give distinct name if needed

# --- Tests ---


# == _load_event_data Tests ==


def test_load_event_data_success(mock_paths):
    """Test loading valid event data from a file."""
    # Create sample data using aware UTC datetimes
    dt1 = datetime(2024, 8, 1, 19, 0, tzinfo=UTC)
    dt2 = datetime(2024, 9, 15, 18, 30, tzinfo=UTC)
    event1_dict = {
        "event_name": "Event 1",
        "venue": "V1",
        "address": "A1",
        "google_maps_link": "g1",
        "event_datetime": dt1.isoformat(),
        "event_deadline": dt1.isoformat(),
        "channel_id": 1,
        "thread_id": 11,
        "message_id": 111,
        "open": True,
        "archived": False,
        "drinks": ["D1"],
    }
    event2_dict = {
        "event_name": "Event 2",
        "venue": "V2",
        "address": "A2",
        "google_maps_link": "g2",
        "event_datetime": dt2.isoformat(),
        "event_deadline": None,
        "channel_id": 2,
        "thread_id": 22,
        "message_id": 222,
        "open": False,
        "archived": False,
        "drinks": [],
    }
    valid_json = json.dumps([event1_dict, event2_dict], indent=4)
    event1_obj = Event(**{**event1_dict, "event_datetime": dt1, "event_deadline": dt1})
    event2_obj = Event(**{**event2_dict, "event_datetime": dt2, "event_deadline": None})

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=valid_json)) as mock_file,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()

        mock_file.assert_called_once_with(mock_paths["events"], "r", encoding="utf-8")
        assert len(events) == 2
        assert events[0] == event1_obj  # Compare dataclass instances
        assert events[1] == event2_obj
        assert events == event_data.EVENT_DATA_CACHE  # Check cache is set
        mock_log.warning.assert_not_called()
        mock_log.error.assert_not_called()


def test_load_event_data_converts_naive_jst_to_utc(mock_paths):
    """Test loading data with naive datetime assumes JST and converts to UTC."""
    naive_dt_str = "2024-08-01T19:00:00"  # Represents 19:00 JST
    # Use a base dict structure for consistency
    base_dict = {"event_name": "Naive Test", "venue": "V", "address": "A", "google_maps_link": "G"}
    naive_event_dict = {**base_dict, "event_datetime": naive_dt_str, "event_deadline": naive_dt_str}
    naive_json = json.dumps([naive_event_dict])

    # Calculate expected UTC datetime
    naive_dt = datetime.fromisoformat(naive_dt_str)
    expected_utc_dt = naive_dt.replace(tzinfo=JST).astimezone(UTC)

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=naive_json)),
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()
        assert len(events) == 1
        assert events[0].event_datetime == expected_utc_dt
        assert events[0].event_deadline == expected_utc_dt
        # Check debug logs if needed
        assert mock_log.debug.call_count == 2  # Once for dt, once for deadline
        assert "Converted naive datetime" in mock_log.debug.call_args_list[0][0][0]
        assert "Converted naive deadline" in mock_log.debug.call_args_list[1][0][0]


def test_load_event_data_converts_aware_other_tz_to_utc(mock_paths):
    """Test loading data with aware non-UTC datetime converts to UTC."""
    aware_dt_str = "2024-08-01T10:00:00+02:00"  # Represents 10:00 CEST
    base_dict = {"event_name": "Aware Test", "venue": "V", "address": "A", "google_maps_link": "G"}
    aware_event_dict = {**base_dict, "event_datetime": aware_dt_str, "event_deadline": aware_dt_str}
    aware_json = json.dumps([aware_event_dict])

    # Calculate expected UTC datetime
    aware_dt = datetime.fromisoformat(aware_dt_str)
    expected_utc_dt = aware_dt.astimezone(UTC)

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=aware_json)),
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()
        assert len(events) == 1
        assert events[0].event_datetime == expected_utc_dt
        assert events[0].event_deadline == expected_utc_dt
        # Check debug logs if needed
        assert mock_log.debug.call_count == 2
        assert "Converted aware datetime" in mock_log.debug.call_args_list[0][0][0]
        assert "Converted aware deadline" in mock_log.debug.call_args_list[1][0][0]


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
    base_dict = {"event_name": "Invalid DT", "venue": "V", "address": "A", "google_maps_link": "G"}
    invalid_dt_event = {**base_dict, "event_datetime": "not-a-datetime"}
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
        assert events[0].event_name == "Invalid DT"  # Other fields should be loaded
        mock_log.warning.assert_called_once()
        assert "Could not parse/convert ISO datetime" in mock_log.warning.call_args[0][0]
        assert "'not-a-datetime'" in mock_log.warning.call_args[0][0]


def test_load_event_data_old_format_missing_deadline(mock_paths):
    """Test loading data from old format missing deadline and channel_id."""
    old_format_dict = {
        "event_name": "Old Event",
        "venue": "Venue Old",
        "address": "Addr Old",
        "google_maps_link": "gmap_old",
        "event_datetime": NOW_UTC.isoformat(),
        # Missing event_deadline
        "message": "Msg Old",
        "channel_id": 999,  # This was thread_id in old format potentially
        "message_id": 888,
        "open": True,
        "archived": False,
        "drinks": ["Water"],
    }
    old_json = json.dumps([old_format_dict])

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=old_json)),
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()

        assert len(events) == 1
        event = events[0]
        assert event.event_name == "Old Event"
        assert event.event_deadline is None  # Should be None
        assert event.channel_id is None  # Should be None (as per backward compat logic)
        assert event.thread_id == 999  # Should take the old channel_id as thread_id
        assert event.message_id == 888
        assert event.event_datetime == NOW_UTC  # Make sure datetime still parses
        mock_log.info.assert_called_once()
        assert "Found old events.json format" in mock_log.info.call_args[0][0]


def test_load_event_data_invalid_deadline(mock_paths):
    """Test loading data with an invalid deadline string."""
    base_dict = {"event_name": "Invalid DL", "venue": "V", "address": "A", "google_maps_link": "G"}
    invalid_dl_event = {**base_dict, "event_deadline": "not-a-deadline"}
    invalid_json = json.dumps([invalid_dl_event])

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=invalid_json)),
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()

        assert len(events) == 1
        assert events[0].event_deadline is None  # Deadline should be None
        assert events[0].event_name == "Invalid DL"
        mock_log.warning.assert_called_once()
        assert "Could not parse/convert ISO deadline" in mock_log.warning.call_args[0][0]
        assert "'not-a-deadline'" in mock_log.warning.call_args[0][0]


def test_load_event_data_missing_required_field(mock_paths):
    """Test loading data where a dict is missing a required Event field."""
    bad_event_dict = {"venue": "V", "address": "A"}  # Missing event_name
    # Use a valid event dict for comparison
    valid_event_dict = {"event_name": "Valid Event", "venue": "V", "address": "A", "google_maps_link": "G"}
    valid_event_obj = Event(**valid_event_dict)
    bad_json = json.dumps([bad_event_dict, valid_event_dict])

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=bad_json)),
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        events = event_data._load_event_data()

        assert len(events) == 1  # Only the valid event should be loaded
        assert events[0] == valid_event_obj
        mock_log.error.assert_called_once()
        assert "Skipping event entry due to missing or empty 'event_name'." in mock_log.error.call_args[0][0]
        # Check that the problematic dict is logged (or part of it)
        assert "'venue': 'V'" in str(mock_log.error.call_args)


# == load_event_data Tests ==


def test_load_event_data_uses_cache(sample_event_list):
    """Test that load_event_data returns cache if populated."""
    # Pre-populate cache
    event_data.EVENT_DATA_CACHE = sample_event_list

    # Patch _load_event_data to ensure it's NOT called
    with patch("offkai_bot.data.event._load_event_data") as mock_internal_load:
        events = event_data.load_event_data()
        assert events == sample_event_list
        mock_internal_load.assert_not_called()


def test_load_event_data_loads_if_cache_none(sample_event_list):
    """Test that load_event_data calls _load_event_data if cache is None."""
    assert event_data.EVENT_DATA_CACHE is None  # Ensure cache is empty

    # Patch _load_event_data to track calls and return something
    with patch("offkai_bot.data.event._load_event_data", return_value=sample_event_list) as mock_internal_load:
        events = event_data.load_event_data()
        assert events == sample_event_list
        mock_internal_load.assert_called_once()


# == save_event_data Tests ==


def test_save_event_data_success(mock_paths, sample_event_list):
    """Test saving valid event data."""
    event_data.EVENT_DATA_CACHE = sample_event_list  # Populate cache

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
    assert event_data.EVENT_DATA_CACHE is None

    with patch("builtins.open") as mock_file_constructor, patch("offkai_bot.data.event._log") as mock_log:
        event_data.save_event_data()

        mock_file_constructor.assert_not_called()  # Should not attempt to open file
        mock_log.error.assert_called_once()
        assert "Attempted to save event data before loading" in mock_log.error.call_args[0][0]


def test_save_event_data_os_error(mock_paths, sample_event_list):
    """Test handling OS error during file writing."""
    event_data.EVENT_DATA_CACHE = sample_event_list  # Populate cache
    m_open = mock_open()
    m_open.side_effect = OSError("Disk full")  # Simulate error on open('w')

    with patch("builtins.open", m_open), patch("offkai_bot.data.event._log") as mock_log:
        event_data.save_event_data()

        mock_log.error.assert_called_once()
        assert "Error writing event data" in mock_log.error.call_args[0][0]
        assert mock_paths["events"] in mock_log.error.call_args[0][0]
        assert "Disk full" in str(mock_log.error.call_args)


# == get_event Tests ==
# Use prepopulated_event_cache fixture which sets cache and patches load_event_data


def test_get_event_found(prepopulated_event_cache, sample_event_list):
    """Test getting an existing event by name (case-insensitive)."""
    # prepopulated_event_cache ensures cache is loaded with sample_event_list
    event1 = sample_event_list[0]
    event2 = sample_event_list[1]

    found_event = event_data.get_event(event1.event_name.lower())  # Use different case
    assert found_event == event1

    found_event_exact = event_data.get_event(event2.event_name)
    assert found_event_exact == event2


def test_get_event_not_found(prepopulated_event_cache):
    """Test getting a non-existent event raises EventNotFoundError."""
    # prepopulated_event_cache ensures cache is loaded
    non_existent_name = "NonExistent Event"

    with pytest.raises(EventNotFoundError) as exc_info:
        event_data.get_event(non_existent_name)

    assert exc_info.value.event_name == non_existent_name
    assert f"Event '{non_existent_name}' not found." in str(exc_info.value)


# == add_event Tests ==


def test_add_event():
    """Test adding a new event to the cache."""
    initial_cache_state = []  # Start with empty cache simulation
    event_data.EVENT_DATA_CACHE = initial_cache_state  # Set it (though clear_caches does this too)

    # add_event calls load_event_data internally, so patch it to return our list
    with (
        patch("offkai_bot.data.event.load_event_data", return_value=initial_cache_state) as mock_load,
        patch("offkai_bot.data.event.save_event_data") as mock_save,  # Ensure save is NOT called
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        new_event_obj = event_data.add_event(
            event_name="New Event",
            venue="New Venue",
            address="New Addr",
            google_maps_link="new_gmap",
            event_datetime=NOW_UTC,
            event_deadline=LATER_UTC,
            thread_id=12345,
            channel_id=67890,
            drinks_list=["Juice"],
            announce_msg="Announcement!",
        )

        # Assertions
        assert isinstance(new_event_obj, Event)
        assert new_event_obj.event_name == "New Event"
        assert new_event_obj.event_datetime == NOW_UTC
        assert new_event_obj.event_deadline == LATER_UTC
        # ... other property checks ...

        mock_load.assert_called_once()  # Check load was called to get the cache list
        assert len(initial_cache_state) == 1  # Check the list object was modified
        assert initial_cache_state[0] == new_event_obj
        assert event_data.EVENT_DATA_CACHE is initial_cache_state  # Check global var points to it

        mock_save.assert_not_called()  # IMPORTANT: add_event should not save
        mock_log.info.assert_called_once()
        assert "'New Event' added to cache" in mock_log.info.call_args[0][0]


def test_add_event_no_deadline():
    """Test adding a new event without specifying a deadline."""
    initial_cache_state = []
    event_data.EVENT_DATA_CACHE = initial_cache_state

    with (
        patch("offkai_bot.data.event.load_event_data", return_value=initial_cache_state),
        patch("offkai_bot.data.event.save_event_data"),  # Mock save
        patch("offkai_bot.data.event._log"),
    ):
        new_event_obj = event_data.add_event(
            event_name="No Deadline Event",
            venue="Venue",
            address="Addr",
            google_maps_link="gmap",
            event_datetime=NOW_UTC,  # event_deadline omitted
            thread_id=111,
            channel_id=222,
            drinks_list=[],
        )
        assert new_event_obj.event_deadline is None
        assert new_event_obj.event_datetime == NOW_UTC
        assert len(initial_cache_state) == 1
        assert initial_cache_state[0] == new_event_obj


# == update_event_details Tests ==


def test_update_event_details_success_single_field():
    """Test successfully updating a single field (venue)."""
    test_event = copy.deepcopy(BASE_EVENT_OBJ)  # Use clean copy for modification
    new_venue = "Updated Venue"

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event),
        patch("offkai_bot.data.event.parse_event_datetime") as mock_parse_dt,
        patch("offkai_bot.data.event.parse_drinks") as mock_parse_drinks,
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        updated_event = event_data.update_event_details(event_name=test_event.event_name, venue=new_venue)

        assert updated_event is test_event  # Should modify in place
        assert updated_event.venue == new_venue
        assert updated_event.address == BASE_EVENT_OBJ.address  # Check others unchanged
        mock_parse_dt.assert_not_called()
        mock_parse_drinks.assert_not_called()
        mock_save.assert_not_called()
        mock_log.info.assert_called_once_with(f"Event '{test_event.event_name}' details updated in cache.")


def test_update_event_details_success_multiple_fields():
    """Test successfully updating multiple fields including date, deadline, drinks."""
    test_event = copy.deepcopy(BASE_EVENT_OBJ)
    new_addr = "Updated Addr"
    new_date_str = "2025-01-01 10:00"
    new_deadline_str = "2024-12-31 23:59"
    new_drinks_str = "Coke, Pepsi"

    # Expected parsed values (must be aware UTC)
    expected_new_date_utc = datetime(2025, 1, 1, 10, 0, 0).replace(tzinfo=JST).astimezone(UTC)
    expected_new_deadline_utc = datetime(2024, 12, 31, 23, 59, 0).replace(tzinfo=JST).astimezone(UTC)
    expected_new_drinks = ["Coke", "Pepsi"]

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event),
        patch("offkai_bot.data.event.parse_event_datetime") as mock_parse_dt,
        patch("offkai_bot.data.event.parse_drinks") as mock_parse_drinks,
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        mock_parse_dt.side_effect = [expected_new_date_utc, expected_new_deadline_utc]
        mock_parse_drinks.return_value = expected_new_drinks

        updated_event = event_data.update_event_details(
            event_name=test_event.event_name,
            address=new_addr,
            date_time_str=new_date_str,
            deadline_str=new_deadline_str,
            drinks_str=new_drinks_str,
        )

        assert updated_event.address == new_addr
        assert updated_event.event_datetime == expected_new_date_utc
        assert updated_event.event_deadline == expected_new_deadline_utc
        assert updated_event.drinks == expected_new_drinks
        assert updated_event.venue == BASE_EVENT_OBJ.venue  # Check unchanged field

        mock_parse_dt.assert_any_call(new_date_str)
        mock_parse_dt.assert_any_call(new_deadline_str)
        assert mock_parse_dt.call_count == 2
        mock_parse_drinks.assert_called_once_with(new_drinks_str)
        mock_save.assert_not_called()
        mock_log.info.assert_called_once()


def test_update_event_details_no_changes():
    """Test calling update with no actual changes raises NoChangesProvidedError."""
    test_event = copy.deepcopy(BASE_EVENT_OBJ)

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event),
        patch("offkai_bot.data.event.parse_event_datetime"),
        patch("offkai_bot.data.event.parse_drinks"),
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        with pytest.raises(NoChangesProvidedError):
            event_data.update_event_details(
                event_name=test_event.event_name,
                venue=test_event.venue,  # Provide same venue
            )
        mock_save.assert_not_called()
        mock_log.info.assert_not_called()


def test_update_event_details_no_changes_with_parsing():
    """Test update raises NoChangesProvidedError even if parsing happens but result is same."""
    test_event = copy.deepcopy(BASE_EVENT_OBJ)
    same_date_str, same_deadline_str, same_drinks_str = "same date", "same deadline", "same drinks"

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event),
        patch("offkai_bot.data.event.parse_event_datetime") as mock_parse_dt,
        patch("offkai_bot.data.event.parse_drinks") as mock_parse_drinks,
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        mock_parse_dt.side_effect = [test_event.event_datetime, test_event.event_deadline]
        mock_parse_drinks.return_value = test_event.drinks

        with pytest.raises(NoChangesProvidedError):
            event_data.update_event_details(
                event_name=test_event.event_name,
                date_time_str=same_date_str,
                deadline_str=same_deadline_str,
                drinks_str=same_drinks_str,
            )

        mock_parse_dt.assert_any_call(same_date_str)
        mock_parse_dt.assert_any_call(same_deadline_str)
        mock_parse_drinks.assert_called_once_with(same_drinks_str)
        mock_save.assert_not_called()
        mock_log.info.assert_not_called()


def test_update_event_details_archived_event():
    """Test updating an archived event raises EventArchivedError."""
    test_event_archived = copy.deepcopy(EVENT_ARCHIVED)  # Use the specific state object

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event_archived),
        patch("offkai_bot.data.event.parse_event_datetime"),
        patch("offkai_bot.data.event.parse_drinks"),
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        with pytest.raises(EventArchivedError) as exc_info:
            event_data.update_event_details(event_name=test_event_archived.event_name, venue="New Venue")

        assert exc_info.value.event_name == test_event_archived.event_name
        assert exc_info.value.action == "modify"
        mock_save.assert_not_called()
        mock_log.info.assert_not_called()


def test_update_event_details_event_not_found():
    """Test updating a non-existent event raises EventNotFoundError."""
    event_name = "I Don't Exist"
    # Patch get_event directly to raise the error
    with patch("offkai_bot.data.event.get_event", side_effect=EventNotFoundError(event_name)) as mock_get:
        with pytest.raises(EventNotFoundError):
            event_data.update_event_details(event_name=event_name, venue="Doesn't Matter")
        mock_get.assert_called_once_with(event_name)  # Verify get_event was called


def test_update_event_details_invalid_datetime_format():
    """Test that InvalidDateTimeFormatError from parser propagates."""
    test_event = copy.deepcopy(BASE_EVENT_OBJ)
    invalid_date_str = "invalid format"

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event),
        patch("offkai_bot.data.event.parse_event_datetime") as mock_parse_dt,
        patch("offkai_bot.data.event.parse_drinks"),
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        mock_parse_dt.side_effect = InvalidDateTimeFormatError()

        with pytest.raises(InvalidDateTimeFormatError):
            event_data.update_event_details(event_name=test_event.event_name, date_time_str=invalid_date_str)
        mock_parse_dt.assert_called_once()
        mock_save.assert_not_called()
        mock_log.info.assert_not_called()


# == set_event_open_status Tests ==


def test_set_event_open_status_open_to_close():
    """Test closing an open event."""
    test_event = copy.deepcopy(EVENT_OPEN_NOT_ARCHIVED)  # Starts open
    assert test_event.open is True

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event),
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        updated_event = event_data.set_event_open_status(test_event.event_name, target_open_status=False)

        assert updated_event is test_event
        assert updated_event.open is False
        mock_save.assert_not_called()
        mock_log.info.assert_called_once_with(f"Event '{test_event.event_name}' marked as closed in cache.")


def test_set_event_open_status_close_to_open():
    """Test opening a closed event."""
    test_event = copy.deepcopy(EVENT_CLOSED_NOT_ARCHIVED)  # Starts closed
    assert test_event.open is False

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event),
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        updated_event = event_data.set_event_open_status(test_event.event_name, target_open_status=True)

        assert updated_event is test_event
        assert updated_event.open is True
        mock_save.assert_not_called()
        mock_log.info.assert_called_once_with(f"Event '{test_event.event_name}' marked as open in cache.")


def test_set_event_open_status_already_open():
    """Test trying to open an already open event raises EventAlreadyOpenError."""
    test_event = copy.deepcopy(EVENT_OPEN_NOT_ARCHIVED)  # Starts open

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event),
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        with pytest.raises(EventAlreadyOpenError) as exc_info:
            event_data.set_event_open_status(test_event.event_name, target_open_status=True)

        assert exc_info.value.event_name == test_event.event_name
        assert test_event.open is True  # State unchanged
        mock_save.assert_not_called()
        mock_log.info.assert_not_called()


def test_set_event_open_status_already_closed():
    """Test trying to close an already closed event raises EventAlreadyClosedError."""
    test_event = copy.deepcopy(EVENT_CLOSED_NOT_ARCHIVED)  # Starts closed

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event),
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        with pytest.raises(EventAlreadyClosedError) as exc_info:
            event_data.set_event_open_status(test_event.event_name, target_open_status=False)

        assert exc_info.value.event_name == test_event.event_name
        assert test_event.open is False  # State unchanged
        mock_save.assert_not_called()
        mock_log.info.assert_not_called()


def test_set_event_open_status_archived_event():
    """Test changing status of an archived event raises EventArchivedError."""
    test_event_archived = copy.deepcopy(EVENT_ARCHIVED)

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event_archived),
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        # Try to open
        with pytest.raises(EventArchivedError) as exc_info_open:
            event_data.set_event_open_status(test_event_archived.event_name, target_open_status=True)
        assert exc_info_open.value.event_name == test_event_archived.event_name
        assert exc_info_open.value.action == "open"

        # Try to close
        with pytest.raises(EventArchivedError) as exc_info_close:
            event_data.set_event_open_status(test_event_archived.event_name, target_open_status=False)
        assert exc_info_close.value.event_name == test_event_archived.event_name
        assert exc_info_close.value.action == "close"

        mock_save.assert_not_called()
        mock_log.info.assert_not_called()


def test_set_event_open_status_event_not_found():
    """Test setting status for a non-existent event raises EventNotFoundError."""
    event_name = "I Don't Exist"
    with patch("offkai_bot.data.event.get_event", side_effect=EventNotFoundError(event_name)) as mock_get:
        with pytest.raises(EventNotFoundError):
            event_data.set_event_open_status(event_name=event_name, target_open_status=True)
        mock_get.assert_called_once_with(event_name)


# == archive_event Tests ==
# Similar setup to status tests.


def test_archive_event_success_open_event():
    """Test archiving an open, non-archived event."""
    test_event = copy.deepcopy(EVENT_OPEN_NOT_ARCHIVED)  # Starts open, not archived
    assert test_event.open is True and test_event.archived is False

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event),
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        updated_event = event_data.archive_event(test_event.event_name)

        assert updated_event is test_event
        assert updated_event.archived is True
        assert updated_event.open is False  # Should be forced closed
        mock_save.assert_not_called()
        mock_log.info.assert_called_once_with(
            f"Event '{test_event.event_name}' marked as archived (and closed) in cache."
        )


def test_archive_event_success_closed_event():
    """Test archiving a closed, non-archived event."""
    test_event = copy.deepcopy(EVENT_CLOSED_NOT_ARCHIVED)  # Starts closed, not archived
    assert test_event.open is False and test_event.archived is False

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event),
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        updated_event = event_data.archive_event(test_event.event_name)

        assert updated_event is test_event
        assert updated_event.archived is True
        assert updated_event.open is False  # Stays closed
        mock_save.assert_not_called()
        mock_log.info.assert_called_once_with(
            f"Event '{test_event.event_name}' marked as archived (and closed) in cache."
        )


def test_archive_event_already_archived():
    """Test archiving an already archived event raises EventAlreadyArchivedError."""
    test_event_archived = copy.deepcopy(EVENT_ARCHIVED)  # Starts archived

    with (
        patch("offkai_bot.data.event.get_event", return_value=test_event_archived),
        patch("offkai_bot.data.event.save_event_data") as mock_save,
        patch("offkai_bot.data.event._log") as mock_log,
    ):
        with pytest.raises(EventAlreadyArchivedError) as exc_info:
            event_data.archive_event(test_event_archived.event_name)

        assert exc_info.value.event_name == test_event_archived.event_name
        assert test_event_archived.archived is True  # State unchanged
        mock_save.assert_not_called()
        mock_log.info.assert_not_called()


def test_archive_event_event_not_found():
    """Test archiving a non-existent event raises EventNotFoundError."""
    event_name = "I Don't Exist"
    with patch("offkai_bot.data.event.get_event", side_effect=EventNotFoundError(event_name)) as mock_get:
        with pytest.raises(EventNotFoundError):
            event_data.archive_event(event_name=event_name)
        mock_get.assert_called_once_with(event_name)


# == Event Dataclass Method Tests (Optional but good) ==


def test_event_format_details():
    """Test the format_details method of the Event dataclass."""
    # Simulate 2024-03-15 18:30 JST stored as UTC
    naive_jst = datetime(2024, 3, 15, 18, 30, 0)
    dt_utc = naive_jst.replace(tzinfo=JST).astimezone(UTC)  # Stored value
    # dt_utc is datetime.datetime(2024, 3, 15, 9, 30, tzinfo=datetime.timezone.utc)

    event = Event(
        event_name="Formatting Test",
        venue="Test Venue",
        address="123 Test St",
        google_maps_link="gmap_link",
        event_datetime=dt_utc,
        event_deadline=dt_utc,
        drinks=["Soda", "Water"],
    )

    expected_ts = int(dt_utc.timestamp())

    expected = (
        "📅 **Event Name**: Formatting Test\n"
        "🍽️ **Venue**: Test Venue\n"
        "📍 **Address**: 123 Test St\n"
        "🌎 **Google Maps Link**: gmap_link\n"
        "🕑 **Date and Time**: 2024-03-15 18:30 JST\n"  # Assumes JST formatting
        f"📅 **Deadline**: <t:{expected_ts}:F> (<t:{expected_ts}:R>)\n"
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
        event_deadline=None,
        drinks=[],
    )
    expected = (
        "📅 **Event Name**: Minimal Test\n"
        "🍽️ **Venue**: Min Venue\n"
        "📍 **Address**: Min Addr\n"
        "🌎 **Google Maps Link**: min_gmap\n"
        "🕑 **Date and Time**: Not Set\n"
        "📅 **Deadline**: Not Set\n"
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
    # Simulate 2024-07-20 20:00 JST stored as UTC
    naive_jst = datetime(2024, 7, 20, 20, 0, 0)
    dt_utc = naive_jst.replace(tzinfo=JST).astimezone(UTC)

    event = Event(
        event_name="Message Test Event",
        venue="Test Cafe",
        address="456 Test Ave",
        google_maps_link="gmap_link_msg",
        event_datetime=dt_utc,  # Use aware UTC
        event_deadline=None,  # No deadline in this test
        drinks=["Coffee", "Tea"],
    )
    actual_message = create_event_message(event)

    # Expected details (assuming display as JST)
    expected_details = (
        "📅 **Event Name**: Message Test Event\n"
        "🍽️ **Venue**: Test Cafe\n"
        "📍 **Address**: 456 Test Ave\n"
        "🌎 **Google Maps Link**: gmap_link_msg\n"
        "🕑 **Date and Time**: 2024-07-20 20:00 JST\n"  # Displayed as JST
        "📅 **Deadline**: Not Set\n"
        "🍺 **Drinks**: Coffee, Tea"
    )
    expected_message = f"{expected_details}\n\n{OFFKAI_MESSAGE}\nClick the button below to confirm your attendance!"
    assert actual_message == expected_message


def test_create_event_message_with_deadline():
    # Simulate event/deadline times (e.g., JST) stored as UTC
    event_naive_jst = datetime(2024, 8, 1, 12, 0, 0)
    deadline_naive_jst = datetime(2024, 7, 25, 23, 59, 0)
    event_dt_utc = event_naive_jst.replace(tzinfo=JST).astimezone(UTC)
    deadline_dt_utc = deadline_naive_jst.replace(tzinfo=JST).astimezone(UTC)

    expected_ts = int(deadline_dt_utc.timestamp())  # Calculate from UTC object: 1721919540

    event = Event(
        event_name="Deadline Message Test",
        venue="V",
        address="A",
        google_maps_link="G",
        event_datetime=event_dt_utc,  # Use aware UTC
        event_deadline=deadline_dt_utc,  # Use aware UTC
        drinks=["Test Drink"],
    )
    actual_message = create_event_message(event)

    expected_deadline_str = f"<t:{expected_ts}:F> (<t:{expected_ts}:R>)"
    expected_details = (
        f"📅 **Event Name**: Deadline Message Test\n"
        f"🍽️ **Venue**: V\n"
        f"📍 **Address**: A\n"
        f"🌎 **Google Maps Link**: G\n"
        f"🕑 **Date and Time**: 2024-08-01 12:00 JST\n"  # Displayed as JST
        f"📅 **Deadline**: {expected_deadline_str}\n"  # Check the formatted string
        f"🍺 **Drinks**: Test Drink"
    )
    expected_message = f"{expected_details}\n\n{OFFKAI_MESSAGE}\nClick the button below to confirm your attendance!"
    assert actual_message == expected_message
