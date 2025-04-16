# tests/conftest.py
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from offkai_bot.data import event as event_data
from offkai_bot.data import response as response_data
from offkai_bot.data.event import Event


@pytest.fixture(scope="module")  # Change scope to "module"
def mock_config(tmp_path_factory):  # Use tmp_path_factory (session-scoped)
    """Provides mock config pointing to temporary files for a module."""
    # Create a unique temp directory for this module's run
    module_tmp_dir = tmp_path_factory.mktemp("data_module")
    events_file = module_tmp_dir / "test_events.json"
    responses_file = module_tmp_dir / "test_responses.json"
    return {
        "EVENTS_FILE": str(events_file),
        "RESPONSES_FILE": str(responses_file),
        # Add other necessary mock config values if needed by other modules
    }


@pytest.fixture(autouse=True)  # Automatically used by all tests
def clear_caches():
    """Fixture to clear the data caches before and after each test."""
    # Before test
    event_data.EVENT_DATA_CACHE = None
    response_data.RESPONSE_DATA_CACHE = None
    yield  # Test runs here
    # After test
    event_data.EVENT_DATA_CACHE = None
    response_data.RESPONSE_DATA_CACHE = None


@pytest.fixture
def mock_paths(mock_config):
    """Provides the paths used in the mock config."""
    return {
        "events": mock_config["EVENTS_FILE"],
        "responses": mock_config["RESPONSES_FILE"],
    }


@pytest.fixture(scope="module", autouse=True)
def mock_config_patch(mock_config):
    """Patches get_config for the duration of the test module."""
    with (
        patch("offkai_bot.data.event.get_config", return_value=mock_config),
        patch("offkai_bot.data.response.get_config", return_value=mock_config),
    ):  # Also patch for response if needed indirectly
        yield


@pytest.fixture
def sample_event_list():
    """Provides a list of sample Event objects."""
    # Using fixed datetimes for consistency
    dt1 = datetime(2024, 8, 1, 19, 0, tzinfo=UTC)
    dt2 = datetime(2024, 9, 15, 18, 30, tzinfo=UTC)
    return [
        Event(
            event_name="Summer Bash",
            venue="Beach Cafe",
            address="1 Beach Rd",
            google_maps_link="g1",
            event_datetime=dt1,
            event_deadline=dt1,
            channel_id=1001,
            thread_id=1501,
            message_id=2001,
            open=True,
            archived=False,
            drinks=["Juice", "Soda"],
        ),
        Event(
            event_name="Autumn Meetup",
            venue="Park Pavilion",
            address="2 Park Ln",
            google_maps_link="g2",
            event_datetime=dt2,
            event_deadline=dt2,
            channel_id=1002,
            thread_id=1502,
            message_id=2002,
            open=False,
            archived=False,
            drinks=[],
        ),
        Event(
            event_name="Archived Party",
            venue="Old Hall",
            address="3 Past St",
            google_maps_link="g3",
            event_datetime=None,
            event_deadline=None,
            channel_id=1003,
            thread_id=1503,
            message_id=2003,
            open=False,
            archived=True,
            drinks=[],
        ),
    ]


@pytest.fixture
def prepopulated_event_cache(sample_event_list):
    """Fixture that populates the event cache and returns the list."""
    event_data.EVENT_DATA_CACHE = sample_event_list
    # Ensure load_event_data returns this cache if called
    with patch("offkai_bot.data.event.load_event_data", return_value=sample_event_list):
        yield sample_event_list


@pytest.fixture
def mock_thread():
    """Fixture for a mock discord.Thread."""
    thread = MagicMock(spec=discord.Thread)
    # Use a common ID or make it less specific if needed,
    # but 1001 matches the first sample event which is often useful.
    thread.id = 1001
    thread.mention = f"<#{thread.id}>"
    thread.send = AsyncMock()  # Mock the send method
    thread.edit = AsyncMock()
    thread.remove_user = AsyncMock()
    thread.fetch_message = AsyncMock()
    thread.archived = False
    return thread
